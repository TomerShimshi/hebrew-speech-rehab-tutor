"""FastAPI entrypoint: `uvicorn app.main:app`."""

import datetime as dt
import hashlib
import json
from typing import Literal
import time
from functools import lru_cache
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from google import genai

from app.agent.memory_update import run_memory_update
from app.auth import User, require_caregiver, verify_user, verify_sweeper
from app.config import Settings, get_settings
from app.live_token import create_live_token
from app.llm import generate, text_client
from app.patient_profile import PatientProfileLoader, extract_vocabulary
from app.prompt_archive import PromptArchive
from app.prompts import render_tutor_prompt
from app.rate_limit import SlidingWindowLimiter
from app.store import ACTIVE, FirestoreSessionStore, SessionStore
from app.transcripts import EndRequest, TurnsBatch

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Hebrew Speech Rehab Tutor")


@app.middleware("http")
async def no_stale_assets(request: Request, call_next):
    # Without this, browsers may keep running an old app.js after a deploy. "no-cache" still
    # allows caching, but revalidates (cheap 304) on every load.
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-cache")
    return response


# Not /healthz: Cloud Run reserves paths ending in "z" and 404s them before they reach the app.
@app.get("/api/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    # Report only whether the key is present -- never its value.
    return {"status": "ok", "gemini_key_configured": bool(settings.gemini_api_key)}


def get_genai_client(settings: Settings = Depends(get_settings)) -> genai.Client:
    if not settings.gemini_api_key:
        raise HTTPException(status_code=503, detail="Gemini API key is not configured")
    return _client_for(settings.gemini_api_key)


@lru_cache
def _client_for(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


@lru_cache
def get_profile_loader() -> PatientProfileLoader:
    return PatientProfileLoader(get_settings())


@lru_cache
def get_token_limiter() -> SlidingWindowLimiter:
    return SlidingWindowLimiter(get_settings().token_rate_limit_per_hour, window_s=3600)


@lru_cache
def get_store() -> SessionStore:
    return FirestoreSessionStore()


@lru_cache
def get_prompt_archive() -> PromptArchive:
    return PromptArchive(get_settings().prompt_archive_uri)


def get_text_client(settings: Settings = Depends(get_settings)):
    if not settings.gemini_api_key:
        raise HTTPException(status_code=503, detail="Gemini API key is not configured")
    return text_client(settings.gemini_api_key)


def _bounded_generate(budget_s: float):
    """generate() with one shared time budget across all calls of a memory update."""
    deadline = time.monotonic() + budget_s

    def bounded(client, models, contents, config=None):
        return generate(client, models, contents, config, deadline=deadline)

    return bounded


@app.get("/api/config")
def public_config(settings: Settings = Depends(get_settings)) -> dict:
    # The Firebase web config is public by design; access is enforced by verify_user.
    return {
        "firebase": {
            "apiKey": settings.firebase_api_key,
            "authDomain": settings.firebase_auth_domain,
            "projectId": settings.gcp_project_id,
            "appId": settings.firebase_app_id,
        }
    }


@app.get("/api/me")
def me(user: User = Depends(verify_user), settings: Settings = Depends(get_settings)) -> dict:
    # Lets the page tell right after sign-in whether this account is allowed (and a caregiver).
    return {"email": user.email, "is_caregiver": user.email in settings.caregiver_email_set}


def memory_block(memory: dict | None) -> str:
    """The tutor-facing part of this account's memory (written after each session, 04)."""
    if not memory or not memory.get("memory_prompt"):
        return ""
    text = memory["memory_prompt"].strip()
    focus = memory.get("focus_next_session") or []
    if focus:
        text += "\n\nFocus for this session:\n" + "\n".join(f"- {f}" for f in focus)
    return text


def patient_id_for(user: User) -> str:
    # Every account is its own record (sessions, transcripts, memory), keyed by login email,
    # so memories never mix -- e.g. Tomer's test sessions vs Dad's real ones.
    return user.email


def _own_active_session(store: SessionStore, settings: Settings, user: User, sid: str) -> dict:
    session = store.get_session(patient_id_for(user), sid)
    if session is None or session.get("user_email") != user.email:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.get("status") != ACTIVE:
        raise HTTPException(status_code=409, detail="Session already ended")
    return session


@app.post("/api/session/start")
def start_session(
    # Set when reconnecting mid-session (Live connections last ~10 min): it's baked into the
    # new token so the conversation continues where it left off -- in the same session doc.
    resume_handle: str | None = Body(default=None, embed=True, max_length=4096),
    session_id: str | None = Body(default=None, embed=True, max_length=64),
    user: User = Depends(verify_user),
    settings: Settings = Depends(get_settings),
    client: genai.Client = Depends(get_genai_client),
    limiter: SlidingWindowLimiter = Depends(get_token_limiter),
    profile: PatientProfileLoader = Depends(get_profile_loader),
    store: SessionStore = Depends(get_store),
    archive: PromptArchive = Depends(get_prompt_archive),
) -> dict:
    if not limiter.allow():
        raise HTTPException(status_code=429, detail="Too many sessions, try again later")
    if session_id:
        _own_active_session(store, settings, user, session_id)  # reconnect: same session
    profile_text = profile.get()
    prompt = render_tutor_prompt(
        patient_profile=profile_text,
        memory_prompt=memory_block(store.get_memory(patient_id_for(user))),
    )
    live = create_live_token(
        settings,
        prompt,
        client,
        resume_handle=resume_handle,
        vocabulary=extract_vocabulary(profile_text),
    )
    if not session_id:
        # A session still "active" means its tab was closed without ending: close it out.
        store.mark_abandoned(patient_id_for(user))
        session_id = store.create_session(
            patient_id_for(user),
            user_email=user.email,
            model=live.model,
            prompt_version=prompt.version,
        )
        # Debugging aid: keep the exact prompt this session's tutor got (private bucket).
        prompt_uri = archive.save(
            pid=patient_id_for(user), sid=session_id, prompt_text=prompt.text,
            meta={"account": user.email, "model": live.model, "prompt_version": prompt.version},
        )
        if prompt_uri:
            store.update_session(patient_id_for(user), session_id, {"prompt_uri": prompt_uri})
    return {
        "session_id": session_id,
        "token": live.token,
        "model": live.model,
        "ws_url": live.ws_url,
        "expires_at": live.expires_at.isoformat(),
        "prompt_version": prompt.version,
    }


@app.post("/api/session/{session_id}/turns")
def save_turns(
    session_id: str,
    batch: TurnsBatch,
    user: User = Depends(verify_user),
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
) -> dict:
    # Deterministic transcript saving: plain code, upsert by seq (retries never duplicate).
    _own_active_session(store, settings, user, session_id)
    store.upsert_turns(patient_id_for(user), session_id, batch.turns)
    return {"saved": len(batch.turns)}


@app.post("/api/session/{session_id}/end")
def end_session(
    session_id: str,
    body: EndRequest,
    user: User = Depends(verify_user),
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
    profile: PatientProfileLoader = Depends(get_profile_loader),
    llm_client=Depends(get_text_client),
) -> dict:
    pid = patient_id_for(user)
    _own_active_session(store, settings, user, session_id)
    store.end_session(pid, session_id, body.reason)
    # Update the tutor's memory now, inside this request (Cloud Run throttles CPU after the
    # response). The browser doesn't wait: it sent this with keepalive and moved on.
    # Failures are recorded and retried by the hourly sweep.
    memory_status = run_memory_update(
        store, llm_client, settings, pid, session_id,
        profile_text=profile.get(), generate_fn=_bounded_generate(settings.memory_end_deadline_s),
    )
    return {"status": "ended", "memory_status": memory_status}


@app.post("/internal/memory/sweep")
def memory_sweep(
    _caller: str = Depends(verify_sweeper),
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
    profile: PatientProfileLoader = Depends(get_profile_loader),
    llm_client=Depends(get_text_client),
) -> dict:
    """Hourly (Cloud Scheduler): update memory for sessions still waiting -- tabs closed
    mid-session, or updates that failed because the models were overloaded."""
    results: dict[str, str] = {}
    budget = settings.memory_sweep_batch
    for pid in store.list_patient_ids():
        for sid in store.pending_memory_sessions(pid, limit=budget - len(results)):
            results[sid] = run_memory_update(
                store, llm_client, settings, pid, sid,
                profile_text=profile.get(), generate_fn=_bounded_generate(240),
            )
        if len(results) >= budget:
            break
    return {"processed": results}


@lru_cache
def asset_version() -> str:
    """Hash of the front-end files: a new deploy with changed assets gets a new version."""
    digest = hashlib.sha256()
    for path in sorted(STATIC_DIR.rglob("*")):
        if path.is_file() and path.suffix in {".js", ".css"}:
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
def index() -> str:
    # Asset URLs carry the version (style.css?v=...), so browsers can never keep using a
    # stale copy after a deploy -- even one cached before we sent Cache-Control headers.
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return html.replace("__ASSET_VERSION__", asset_version())


# ---- caregiver tools: forget memory / delete everything ---------------------------------

@app.get("/api/admin/accounts")
def admin_accounts(
    _caregiver: User = Depends(require_caregiver),
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
) -> dict:
    # Only allowlisted accounts can be managed (their record id is the email).
    return {"accounts": [
        {"email": email, **store.account_overview(email)} for email in sorted(settings.allowed_email_set)
    ]}


@app.post("/api/admin/reset")
def admin_reset(
    email: str = Body(..., embed=True, max_length=320),
    scope: Literal["memory", "everything"] = Body(..., embed=True),
    confirm_email: str = Body(..., embed=True, max_length=320),
    caregiver: User = Depends(require_caregiver),
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
    archive: PromptArchive = Depends(get_prompt_archive),
) -> dict:
    """Forget an account's memory (transcripts kept) or delete all of its data -- e.g. to
    demo the tutor from scratch. The previous memory is backed up to the private bucket."""
    pid = email.strip().lower()
    if pid not in settings.allowed_email_set:
        raise HTTPException(status_code=404, detail="Unknown account")
    if confirm_email.strip().lower() != pid:
        raise HTTPException(status_code=400, detail="Type the account's email to confirm")
    memory = store.get_memory(pid)
    backup_uri = None
    if memory:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_uri = archive.save_backup(
            pid=pid, name=f"{stamp}-{scope}.json",
            content=json.dumps(memory, ensure_ascii=False, indent=2, default=str),
        )
    if scope == "memory":
        store.forget_memory(pid)
        deleted_sessions = 0
    else:
        deleted_sessions = store.delete_account(pid)
    print(f"[admin] {caregiver.email} reset {pid} ({scope}); backup={backup_uri}", flush=True)
    return {"email": pid, "scope": scope, "deleted_sessions": deleted_sessions, "backup": backup_uri}


# Mounted last so API routes take precedence over static files.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
