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

from fastapi import APIRouter, Body, Depends, HTTPException

from app.agent.memory_edit import MemoryEditError, remove_item, restore_version
from app.agent.next_class import build_next_plan
from app.agent.research import personal_terms
from app.auth import User, require_caregiver
from app.class_plan import plan_for_session, render_class_plan
from app.config import Settings, get_settings
from app.games import profile_for
from app.deps import (
    _bounded_generate, games_for, get_games_reader, get_profile_loader, get_prompt_archive, get_store,
    get_text_client,
)
from app.patient_profile import PatientProfileLoader
from app.prompt_archive import PromptArchive
from app.store import ENDED, PLAN_DONE, SessionStore

router = APIRouter(prefix="/api/caregiver", dependencies=[Depends(require_caregiver)])

NOTES_MAX_CHARS = 1500

SESSION_FIELDS = ("id", "status", "started_at", "ended_at", "end_reason", "turn_count", "prompt_version",
                  "summary", "topics", "mood", "highlights", "difficulties", "probe_results",
                  "memory_status", "memory_error", "plan_status", "plan_error")


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
    plan = plan_for_session(store, pid)  # what the next session will really get (built or intro)
    return {
        "email": pid,
        "games_profile": games_profile,
        "notes": notes,
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
