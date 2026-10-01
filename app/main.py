"""FastAPI entrypoint: `uvicorn app.main:app`."""

import hashlib
from functools import lru_cache
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from google import genai

from app.auth import User, verify_user
from app.config import Settings, get_settings
from app.live_token import create_live_token
from app.patient_profile import PatientProfileLoader, extract_vocabulary
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
def me(user: User = Depends(verify_user)) -> dict:
    # Lets the page tell right after sign-in whether this account is allowed.
    return {"email": user.email}


def _own_active_session(store: SessionStore, settings: Settings, user: User, sid: str) -> dict:
    session = store.get_session(settings.patient_id, sid)
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
) -> dict:
    if not limiter.allow():
        raise HTTPException(status_code=429, detail="Too many sessions, try again later")
    if session_id:
        _own_active_session(store, settings, user, session_id)  # reconnect: same session
    profile_text = profile.get()
    prompt = render_tutor_prompt(patient_profile=profile_text)
    live = create_live_token(
        settings,
        prompt,
        client,
        resume_handle=resume_handle,
        vocabulary=extract_vocabulary(profile_text),
    )
    if not session_id:
        # A session still "active" means its tab was closed without ending: close it out.
        store.mark_abandoned(settings.patient_id)
        session_id = store.create_session(
            settings.patient_id,
            user_email=user.email,
            model=live.model,
            prompt_version=prompt.version,
        )
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
    store.upsert_turns(settings.patient_id, session_id, batch.turns)
    return {"saved": len(batch.turns)}


@app.post("/api/session/{session_id}/end")
def end_session(
    session_id: str,
    body: EndRequest,
    user: User = Depends(verify_user),
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
) -> dict:
    _own_active_session(store, settings, user, session_id)
    store.end_session(settings.patient_id, session_id, body.reason)
    return {"status": "ended"}


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


# Mounted last so API routes take precedence over static files.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
