"""Caregiver page API (sub-plan 08): /api/caregiver/*, caregivers only.

Every allowlisted account is its own "patient" (Dad's, Tomer's test account...). Routes take
the account's email in the path; anything not on the allowlist is a 404, and every read or
write touches only that account's records.

Reading: sessions + transcripts, the next lesson, memory (+ history), word bank, research
notes, games suggestions, flags. Actions: rebuild the next lesson now, planner notes, remove
one memory item / restore a version (backed up first), resolve flags, suggestion statuses,
the 4.5 reset. Nothing here posts anywhere outside the app: the GitHub button only gets a
prefilled "new issue" link that the caregiver reviews and submits himself.
"""

import datetime as dt
import json
import re
from typing import Literal
from urllib.parse import urlencode

import yaml
from fastapi import APIRouter, Body, Depends, HTTPException
from google.genai import types
from pydantic import BaseModel

from app.agent.memory_edit import MemoryEditError, remove_item, remove_word, restore_version
from app.agent.memory_update import run_memory_update
from app.agent.next_class import _models, build_next_plan
from app.agent.research import personal_terms
from app.auth import User, require_caregiver
from app.class_plan import plan_for_session, render_class_plan
from app.config import REPO_ROOT, Settings, get_settings
from app.games import profile_for
from app.deps import (
    _bounded_generate, games_for, get_games_reader, get_profile_loader, get_prompt_archive, get_store,
    get_text_client,
)
from app.patient_profile import PatientProfileLoader
from app.session_prompt import build_session_prompt
from app.prompt_archive import PromptArchive
from app.schemas import VoiceSettings
from app.voice_tuning import adjust_after_session, current_settings
from app.store import ACTIVE, ENDED, MEM_DONE, MEM_SKIPPED, PLAN_DONE, SessionStore
from app.transcripts import EndReason

router = APIRouter(prefix="/api/caregiver", dependencies=[Depends(require_caregiver)])

NOTES_MAX_CHARS = 1500
TRANSLATE_PROMPT = REPO_ROOT / "prompts" / "translate_export.yaml"
TRANSLATE_MAX_TEXTS, TRANSLATE_MAX_CHARS = 400, 80_000


class Translations(BaseModel):
    translations: list[str]

SESSION_FIELDS = ("id", "status", "started_at", "ended_at", "end_reason", "turn_count", "prompt_version",
                  "summary", "topics", "mood", "highlights", "difficulties", "probe_results",
                  "memory_status", "memory_error", "plan_status", "plan_error",
                  "memory_model", "plan_model",  # which model did the work (09)
                  "voice_used", "voice_decision")  # the settings it ran with, and the automatic decision after it


def account(email: str, settings: Settings = Depends(get_settings)) -> str:
    pid = email.strip().lower()
    if pid not in settings.allowed_email_set:
        raise HTTPException(status_code=404, detail="Unknown account")
    return pid


def _session_row(session: dict) -> dict:
    row = {k: session.get(k) for k in SESSION_FIELDS}
    plan = session.get("class_plan") or {}
    row["plan_goal"] = (plan.get("primary_goal") or {}).get("type")
    row["plan_type"] = plan.get("plan_type")
    return row


def _word_rows(word_bank: dict) -> list[dict]:
    rows = [{"word": w, **(s or {})} for w, s in (word_bank or {}).items()]
    return sorted(rows, key=lambda r: (r.get("next_due") or "9999", r["word"]))


def _backup(archive: PromptArchive, pid: str, memory: dict | None, why: str) -> str | None:
    if not memory:
        return None
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return archive.save_backup(pid=pid, name=f"{stamp}-{why}.json",
                               content=json.dumps(memory, ensure_ascii=False, indent=2, default=str))


def _scrub(text: str, terms: set[str]) -> str:
    for term in sorted(terms, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(term)}(?!\w)", "[name]", text or "", flags=re.IGNORECASE)
    return text


def github_issue_url(rec: dict, repo: str, terms: set[str]) -> str:
    """A prefilled "new issue" link on the (public) Simon repo: game data only, his names
    scrubbed. Nothing is posted: the caregiver reviews the form on GitHub and submits it."""
    title = _scrub(rec.get("title", ""), terms)
    body = "\n".join([
        f"**Game:** `{rec.get('game_id')}`  ",
        f"**Kind:** {rec.get('kind')}  ",
        f"**Suggested:** {rec.get('times_suggested', 1)} time(s), by the Hebrew speech tutor's lesson planner",
        "", "## Why", _scrub(rec.get("rationale", ""), terms),
        "", "## Evidence (from the game's progress data)", _scrub(rec.get("evidence", ""), terms),
        "", "## Task for Claude Code",
        f"In this repo, address: \"{title}\" for the `{rec.get('game_id')}` game. Read the game's code "
        "and its progress data format first, keep the change small and backward compatible "
        "(existing saved progress must keep working), and add or update tests.",
    ])
    return f"https://github.com/{repo}/issues/new?" + urlencode({"title": f"[{rec.get('game_id')}] {title}",
                                                                   "body": body})


MOOD_SCORE = {"low": 1, "ok": 2, "good": 3}


def _own_share(results: list[dict], kind: str) -> float | None:
    """Share of check-in items of this kind he answered on his own (no hint), 0-100."""
    items = [r for r in results if r.get("kind") == kind]
    if not items:
        return None
    return round(100 * sum(r.get("result") == "uncued" for r in items) / len(items))


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values)) if values else None


def progress_series(sessions: list[dict], word_bank: dict) -> dict:
    """Numbers for the caregiver page's graphs (09). `sessions` newest first, as stored."""
    points = []
    for s in reversed(sessions):  # oldest first, for the x-axis
        results = s.get("probe_results") or []
        mood = MOOD_SCORE.get(s.get("mood") or "")
        if not results and mood is None:
            continue
        points.append({"date": s.get("started_at"), "treated": _own_share(results, "treated"),
                       "untreated": _own_share(results, "untreated"), "items": len(results), "mood": mood})
    with_checkins = [p for p in points if p["items"]]
    recent, before = with_checkins[-5:], with_checkins[-10:-5]
    words = list((word_bank or {}).values())
    return {
        "points": points,
        "compare": {  # last 5 sessions with check-ins vs the 5 before them
            "recent": {"treated": _mean([p["treated"] for p in recent]), "untreated": _mean([p["untreated"] for p in recent]),
                       "sessions": len(recent)},
            "before": {"treated": _mean([p["treated"] for p in before]), "untreated": _mean([p["untreated"] for p in before]),
                       "sessions": len(before)},
        },
        "words": {"total": len(words),
                  "own": sum((w or {}).get("last_result") == "uncued" for w in words),
                  "hint": sum((w or {}).get("last_result") == "cued" for w in words),
                  "not_yet": sum((w or {}).get("last_result") == "failed" for w in words)},
    }


@router.get("/{email}/progress")
def progress(pid: str = Depends(account), store: SessionStore = Depends(get_store)) -> dict:
    return progress_series(store.list_sessions(pid, 30), (store.get_memory(pid) or {}).get("word_bank") or {})


@router.get("/accounts")
def accounts(caregiver: User = Depends(require_caregiver), settings: Settings = Depends(get_settings),
             store: SessionStore = Depends(get_store)) -> dict:
    return {"me": caregiver.email, "accounts": [
        {"email": email, **store.account_overview(email)} for email in sorted(settings.allowed_email_set)
    ]}


@router.get("/{email}/overview")
def overview(pid: str = Depends(account), settings: Settings = Depends(get_settings),
             store: SessionStore = Depends(get_store),
             profile: PatientProfileLoader = Depends(get_profile_loader)) -> dict:
    memory = store.get_memory(pid) or {}
    notes = store.get_notes(pid) or {}
    games_profile = profile_for(pid, settings.simon_profiles)
    terms = personal_terms(memory, f"{profile.get()}\n{notes.get('text', '')}",
                           extra=(pid.split("@")[0], games_profile or ""))
    stored_plan = store.get_next_plan(pid) or {}
    built_after = stored_plan.get("built_after_session")
    plan_model = (store.get_session(pid, built_after) or {}).get("plan_model") if built_after else None
    plan = plan_for_session(store, pid)  # what the next session will really get (built or intro)
    return {
        "email": pid,
        "games_profile": games_profile,
        "notes": notes,
        "settings": {**current_settings(store, settings, pid)[0].model_dump(),
                     "auto_state": (store.get_settings(pid) or {}).get("auto_state") or {}},
        "flags": store.list_flags(pid),
        "memory": {k: memory.get(k) for k in ("memory_prompt", "sections", "focus_next_session",
                                               "sessions_processed", "updated_at", "last_session_id")},
        "word_bank": _word_rows(memory.get("word_bank")),
        "next_plan": {
            "rendered": render_class_plan(plan),
            "plan_type": plan.plan_type if plan else None,
            "built_at": stored_plan.get("built_at"),
            "built_after_session": stored_plan.get("built_after_session"),
            "prompt_version": stored_plan.get("prompt_version"),
            "research": stored_plan.get("research"),
            "notes_used_at": stored_plan.get("notes_used_at"),
            "model": plan_model,
            "notes_applied": stored_plan.get("notes_applied", ""),
        },
        "research_notes": store.recent_technique_notes(pid, 20),
        "recommendations": [{**r, "github_url": github_issue_url(r, settings.simon_repo, terms)}
                            for r in store.list_recommendations(pid)],
    }


@router.get("/{email}/sessions")
def sessions(pid: str = Depends(account), store: SessionStore = Depends(get_store)) -> dict:
    return {"sessions": [_session_row(s) for s in store.list_sessions(pid, 30)]}


@router.get("/{email}/sessions/{sid}")
def session_detail(sid: str, pid: str = Depends(account), store: SessionStore = Depends(get_store)) -> dict:
    session = store.get_session(pid, sid)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    turns = [{k: t.get(k) for k in ("seq", "speaker", "text", "live_text", "t_start_s", "interrupted")}
             for t in store.list_turns(pid, sid)]
    return {"session": _session_row({"id": sid, **session}), "turns": turns}


@router.get("/{email}/sessions/{sid}/prompt")
def session_prompt(sid: str, pid: str = Depends(account), store: SessionStore = Depends(get_store)) -> dict:
    """The exact system instruction the tutor got in that session (stored from 8.5 on)."""
    if store.get_session(pid, sid) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    saved = store.get_session_prompt(pid, sid)
    return {"text": (saved or {}).get("text"), "prompt_version": (saved or {}).get("prompt_version")}


@router.get("/{email}/next-prompt")
def next_prompt(pid: str = Depends(account), settings: Settings = Depends(get_settings),
                store: SessionStore = Depends(get_store),
                profile: PatientProfileLoader = Depends(get_profile_loader),
                games_reader=Depends(get_games_reader)) -> dict:
    """What the tutor would get if this account started a session right now -- built by the
    same function as /api/session/start."""
    built = build_session_prompt(store, settings, pid, profile.get(), games_reader)
    return {"text": built.prompt.text, "prompt_version": built.prompt.version}


@router.get("/{email}/memory/history")
def memory_history(pid: str = Depends(account), store: SessionStore = Depends(get_store)) -> dict:
    return {"versions": [{k: v.get(k) for k in ("version", "memory_prompt", "sections", "updated_at",
                                                 "sessions_processed", "last_session_id")}
                         for v in store.list_memory_history(pid)]}


@router.put("/{email}/notes")
def save_notes(text: str = Body(..., embed=True, max_length=NOTES_MAX_CHARS), pid: str = Depends(account),
               caregiver: User = Depends(require_caregiver), store: SessionStore = Depends(get_store)) -> dict:
    store.save_notes(pid, text.strip(), caregiver.email)
    print(f"[caregiver] {caregiver.email} saved planner notes for {pid} ({len(text.strip())} chars)", flush=True)
    return {"ok": True}


@router.put("/{email}/settings")
def save_settings(voice: VoiceSettings = Body(..., embed=True), pid: str = Depends(account),
                  caregiver: User = Depends(require_caregiver), store: SessionStore = Depends(get_store)) -> dict:
    """Per-account session settings (09); they apply from the account's next session."""
    saved = store.get_settings(pid) or {}  # keep the automatic state (streaks, last decision)
    store.save_settings(pid, {**voice.model_dump(), "auto_state": saved.get("auto_state") or {}}, caregiver.email)
    print(f"[caregiver] {caregiver.email} set {pid}'s voice settings: {voice.model_dump()}", flush=True)
    return {"ok": True}


@router.post("/{email}/flags/{flag_id}/resolve")
def resolve_flag(flag_id: str, pid: str = Depends(account), caregiver: User = Depends(require_caregiver),
                 store: SessionStore = Depends(get_store)) -> dict:
    if not store.resolve_flag(pid, flag_id, caregiver.email):
        raise HTTPException(status_code=404, detail="Flag not found")
    return {"ok": True}


@router.post("/{email}/recommendations/{rec_id}")
def set_recommendation_status(rec_id: str, status: Literal["new", "accepted", "rejected", "done"] = Body(..., embed=True),
                              pid: str = Depends(account), store: SessionStore = Depends(get_store)) -> dict:
    if not store.set_recommendation_status(pid, rec_id, status):
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return {"ok": True}


@router.post("/{email}/memory/remove-item")
def memory_remove_item(
    section: str = Body(..., embed=True, max_length=64),
    item: str = Body(..., embed=True, max_length=2000),
    pid: str = Depends(account),
    caregiver: User = Depends(require_caregiver),
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
    archive: PromptArchive = Depends(get_prompt_archive),
    llm_client=Depends(get_text_client),
) -> dict:
    """Removes one wrong item and rewrites the tutor's summary without it (one model call)."""
    backup = _backup(archive, pid, store.get_memory(pid), "remove-item")
    try:
        memory = remove_item(store, llm_client, settings, pid, section, item, generate_fn=_bounded_generate(90))
    except MemoryEditError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 -- e.g. the models are busy: nothing was changed
        raise HTTPException(status_code=503, detail="The model is busy; nothing was changed. Try again.") from exc
    print(f"[caregiver] {caregiver.email} removed a {section} item from {pid}'s memory; backup={backup}", flush=True)
    return {"ok": True, "memory_prompt": memory["memory_prompt"], "backup": backup}


@router.post("/{email}/word-bank/remove")
def word_bank_remove(
    word: str = Body(..., embed=True, max_length=200),
    pid: str = Depends(account),
    caregiver: User = Depends(require_caregiver),
    store: SessionStore = Depends(get_store),
    archive: PromptArchive = Depends(get_prompt_archive),
) -> dict:
    backup = _backup(archive, pid, store.get_memory(pid), "remove-word")
    try:
        remove_word(store, pid, word)
    except MemoryEditError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    print(f"[caregiver] {caregiver.email} removed a word from {pid}'s word bank; backup={backup}", flush=True)
    return {"ok": True, "backup": backup}


@router.post("/{email}/memory/restore")
def memory_restore(
    version: str = Body(..., embed=True, max_length=200),
    pid: str = Depends(account),
    caregiver: User = Depends(require_caregiver),
    store: SessionStore = Depends(get_store),
    archive: PromptArchive = Depends(get_prompt_archive),
) -> dict:
    backup = _backup(archive, pid, store.get_memory(pid), "restore")
    try:
        restore_version(store, pid, version)
    except MemoryEditError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    print(f"[caregiver] {caregiver.email} restored {pid}'s memory to {version}; backup={backup}", flush=True)
    return {"ok": True, "backup": backup}


@router.post("/{email}/export/translate")
def translate_export(
    texts: list[str] = Body(..., embed=True),
    pid: str = Depends(account),
    settings: Settings = Depends(get_settings),
    llm_client=Depends(get_text_client),
) -> dict:
    """Translates the therapist export's English texts into Hebrew -- one model call. The
    caller falls back to English if this fails."""
    if len(texts) > TRANSLATE_MAX_TEXTS or sum(len(t) for t in texts) > TRANSLATE_MAX_CHARS:
        raise HTTPException(status_code=413, detail="Too much text to translate at once")
    if not texts:
        return {"translations": []}
    prompt = yaml.safe_load(TRANSLATE_PROMPT.read_text(encoding="utf-8"))["system"]
    try:
        result = _bounded_generate(120)(
            llm_client, _models(settings), json.dumps(texts, ensure_ascii=False),
            types.GenerateContentConfig(system_instruction=prompt, response_mime_type="application/json",
                                        response_schema=Translations, temperature=0.2))
        out = result.response.parsed
        if not isinstance(out, Translations):
            out = Translations.model_validate_json(result.response.text)
    except Exception as exc:  # noqa: BLE001 -- the page prints the English version instead
        raise HTTPException(status_code=503, detail="Translation failed; print in English") from exc
    if len(out.translations) != len(texts):
        raise HTTPException(status_code=502, detail="Translation came back incomplete")
    print(f"[caregiver] translated an export for {pid}: {len(texts)} texts, model {result.model}", flush=True)
    return {"translations": out.translations, "model": result.model}


STUCK_ACTIVE_AFTER = dt.timedelta(minutes=20)  # sessions last ~10-15 min: still "active" = tab closed


@router.post("/{email}/sessions/{sid}/process")
def process_session(
    sid: str,
    pid: str = Depends(account),
    caregiver: User = Depends(require_caregiver),
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
    llm_client=Depends(get_text_client),
    profile: PatientProfileLoader = Depends(get_profile_loader),
    games_reader=Depends(get_games_reader),
) -> dict:
    """Process a session now instead of waiting for the hourly sweep: the same steps as the
    end of a session (memory update, voice decision, next lesson) -- picking up where it
    stopped: a step that already finished is not run again (e.g. memory done, plan failed ->
    only the plan). Safe to press twice: the memory update claims the session."""
    session = store.get_session(pid, sid)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.get("status") == ACTIVE:
        started = session.get("started_at")
        if started and dt.datetime.now(dt.timezone.utc) - started < STUCK_ACTIVE_AFTER:
            raise HTTPException(status_code=409, detail="The session may still be running")
        store.end_session(pid, sid, EndReason.abandoned)  # its tab was closed without ending
    bounded = _bounded_generate(settings.memory_end_deadline_s)
    profile_text = profile.get()
    memory_status = session.get("memory_status")
    if memory_status not in (MEM_DONE, MEM_SKIPPED):
        memory_status = run_memory_update(store, llm_client, settings, pid, sid,
                                          profile_text=profile_text, generate_fn=bounded)
    adjust_after_session(store, settings, pid, sid)
    plan_status = (store.get_session(pid, sid) or {}).get("plan_status")
    if memory_status == MEM_DONE and plan_status != PLAN_DONE:
        plan_status = build_next_plan(store, llm_client, settings, pid, sid, profile_text=profile_text,
                                      generate_fn=bounded, games=games_for(pid, settings, games_reader))
    after = store.get_session(pid, sid) or {}
    print(f"[caregiver] {caregiver.email} processed {pid}/{sid}: memory {memory_status}, plan {plan_status}", flush=True)
    return {"memory_status": memory_status, "plan_status": plan_status,
            "error": after.get("memory_error") or after.get("plan_error")}


@router.post("/{email}/plan/rebuild")
def rebuild_plan(
    pid: str = Depends(account),
    caregiver: User = Depends(require_caregiver),
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
    llm_client=Depends(get_text_client),
    profile: PatientProfileLoader = Depends(get_profile_loader),
    games_reader=Depends(get_games_reader),
) -> dict:
    """Builds the next lesson again now, with the code and prompts deployed right now (e.g.
    after a prompt change), from the account's current memory and games. Replaces the saved
    plan only on success; it is tied to the account's latest ended session."""
    if not (store.get_memory(pid) or {}).get("memory_prompt"):
        raise HTTPException(status_code=409, detail="No memory yet: the next session is the intro")
    ended = [s for s in store.list_sessions(pid, 10) if s.get("status") == ENDED]
    if not ended:
        raise HTTPException(status_code=409, detail="No ended session to build after")
    sid = ended[0]["id"]
    status = build_next_plan(store, llm_client, settings, pid, sid, profile_text=profile.get(),
                             generate_fn=_bounded_generate(240), games=games_for(pid, settings, games_reader))
    error = None if status == PLAN_DONE else (store.get_session(pid, sid) or {}).get("plan_error")
    print(f"[caregiver] {caregiver.email} rebuilt the next plan for {pid}: {status}", flush=True)
    return {"plan_status": status, "built_after_session": sid, "error": error}


@router.post("/{email}/reset")
def reset(
    scope: Literal["memory", "everything"] = Body(..., embed=True),
    confirm_email: str = Body(..., embed=True, max_length=320),
    pid: str = Depends(account),
    caregiver: User = Depends(require_caregiver),
    store: SessionStore = Depends(get_store),
    archive: PromptArchive = Depends(get_prompt_archive),
) -> dict:
    """Forget an account's memory (transcripts kept) or delete all of its data -- e.g. to
    demo the tutor from scratch. The previous memory is backed up to the private bucket."""
    if confirm_email.strip().lower() != pid:
        raise HTTPException(status_code=400, detail="Type the account's email to confirm")
    backup_uri = _backup(archive, pid, store.get_memory(pid), scope)
    if scope == "memory":
        store.forget_memory(pid)
        deleted_sessions = 0
    else:
        deleted_sessions = store.delete_account(pid)
    print(f"[caregiver] {caregiver.email} reset {pid} ({scope}); backup={backup_uri}", flush=True)
    return {"email": pid, "scope": scope, "deleted_sessions": deleted_sessions, "backup": backup_uri}
