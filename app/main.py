"""FastAPI entrypoint: `uvicorn app.main:app`."""

import base64
import datetime as dt
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from google import genai

from app.agent.memory_update import run_memory_update
from app.agent.next_class import build_next_plan
from app.games import game_link, profile_for
from app.auth import User, verify_user, verify_sweeper
from app.config import Settings, get_settings
from app.live_token import create_live_token
from app.patient_profile import PatientProfileLoader, extract_vocabulary
from app.prompt_archive import PromptArchive
from app.schemas import VoiceSettings
from app import billing_guard
from app.voice_tuning import adjust_after_session, current_settings
from app.session_prompt import build_session_prompt
from app.rate_limit import SlidingWindowLimiter
from app.store import ACTIVE, MEM_DONE, SessionStore
from app.deps import (  # noqa: F401 -- shared with the caregiver router (tests override these)
    _bounded_generate, games_for, get_audio_store, get_games_reader, get_profile_loader, get_prompt_archive,
    get_push_sender, get_store, get_text_client,
)
from app.reminders import ReminderSettings, run_reminders, subscription_id
from app.audio_store import AUDIO_TYPES, MAX_AUDIO_BYTES
from app.caregiver_api import router as caregiver_router
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
def get_token_limiter() -> SlidingWindowLimiter:
    return SlidingWindowLimiter(get_settings().token_rate_limit_per_hour, window_s=3600)


def homework_buttons(plan, pid: str, settings: Settings) -> list[dict]:
    """Links for the plan's game homework, built in code (never by the model)."""
    profile_name = profile_for(pid, settings.simon_profiles)
    if not plan or not plan.game_homework or not profile_name or not settings.simon_app_url:
        return []
    from app.games import local_catalog
    routes = {g["id"]: g.get("route", "") for g in local_catalog().get("games", [])}
    return [
        {"name_he": h.name_he or h.game_id, "why": h.why,
         "url": game_link(settings.simon_app_url, routes[h.game_id], profile_name)}
        for h in plan.game_homework if routes.get(h.game_id)
    ]


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
def me(user: User = Depends(verify_user), settings: Settings = Depends(get_settings),
       store: SessionStore = Depends(get_store), audio=Depends(get_audio_store)) -> dict:
    # Lets the page tell right after sign-in whether this account is allowed (and a caregiver),
    # and whether its sessions are recorded (the start screen says so -- 09).
    recording = audio.enabled and voice_settings(store, settings, user.email).record_audio
    return {"email": user.email, "is_caregiver": user.email in settings.caregiver_email_set,
            "recording": recording, "paused": billing_guard.is_paused(store),
            "reminder": ReminderSettings(**(store.get_reminder_settings(user.email) or {})).model_dump()}


def voice_settings(store: SessionStore, settings: Settings, pid: str) -> VoiceSettings:
    return current_settings(store, settings, pid)[0]


def patient_id_for(user: User) -> str:
    # Every account is its own record (sessions, transcripts, memory), keyed by login email,
    # so memories never mix -- e.g. Tomer's test sessions vs Dad's real ones.
    return user.email


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def live_minutes_today(store: SessionStore, settings: Settings, pid: str) -> float:
    """Live minutes this account used today (Israel time); each session counts at most its cap."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Jerusalem")
    now = now_utc()
    midnight = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    cap = dt.timedelta(minutes=settings.live_max_session_minutes)
    total = dt.timedelta()
    for s in store.list_sessions(pid, 30):
        started = s.get("started_at")
        if not started or started < midnight:
            continue
        total += min(cap, (s.get("ended_at") or now) - started)
    return total.total_seconds() / 60


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
    games_reader=Depends(get_games_reader),
    audio=Depends(get_audio_store),
) -> dict:
    if billing_guard.is_paused(store):  # soft stop on spending (10): the page says practice is paused
        raise HTTPException(status_code=503, detail="paused")
    if not limiter.allow():
        raise HTTPException(status_code=429, detail="Too many sessions, try again later")
    if session_id:
        session = _own_active_session(store, settings, user, session_id)  # reconnect: same session
        started = session.get("started_at")
        if started and now_utc() - started > dt.timedelta(minutes=settings.live_max_session_minutes):
            raise HTTPException(status_code=409, detail="session_too_long")  # a tab left open: end it
    elif live_minutes_today(store, settings, patient_id_for(user)) >= settings.live_daily_minutes:
        raise HTTPException(status_code=429, detail="daily_limit")
    if not session_id:
        # A session still "active" means its tab was closed without ending: close it out
        # (before the prompt, so "when you last spoke" counts it).
        store.mark_abandoned(patient_id_for(user))
    profile_text = profile.get()
    # The same function builds the caregiver page's "prompt for the next session" (8.5).
    built = build_session_prompt(store, settings, patient_id_for(user), profile_text, games_reader,
                                 exclude_sid=session_id)
    prompt, plan = built.prompt, built.plan
    # Per-account voice settings from the caregiver page (09): silence length, tap-to-talk.
    voice = voice_settings(store, settings, patient_id_for(user))
    live = create_live_token(
        settings,
        prompt,
        client,
        resume_handle=resume_handle,
        vocabulary=extract_vocabulary(profile_text),
        voice=voice,
    )
    if not session_id:
        session_id = store.create_session(
            patient_id_for(user),
            user_email=user.email,
            model=live.model,
            prompt_version=prompt.version,
        )
        # Debugging aid: keep the exact prompt this session's tutor got (private bucket).
        prompt_uri = archive.save(
            pid=patient_id_for(user), sid=session_id, prompt_text=prompt.text,
            meta={"account": user.email, "session_id": session_id, "model": live.model,
                  "prompt_version": prompt.version},
            # e.g. "regular-discourse", "intro", or "no-plan" -- part of the file name
            label=f"{plan.plan_type}-{plan.primary_goal.type.value}" if plan and plan.plan_type == "regular"
            else (plan.plan_type if plan else "no-plan"),
        )
        # ...and in Firestore, for the caregiver page's per-session "prompt" button (8.5).
        store.save_session_prompt(patient_id_for(user), session_id, prompt.text, prompt.version)
        session_fields = {"prompt_uri": prompt_uri} if prompt_uri else {}
        session_fields["voice_used"] = voice.model_dump()  # what this session ran with (09)
        if plan:
            # The memory update scores the check-in items against exactly this plan.
            session_fields.update(class_plan=plan.model_dump(mode="json"), plan_type=plan.plan_type)
        if session_fields:
            store.update_session(patient_id_for(user), session_id, session_fields)
    return {
        "session_id": session_id,
        "token": live.token,
        "model": live.model,
        "ws_url": live.ws_url,
        "expires_at": live.expires_at.isoformat(),
        "prompt_version": prompt.version,
        "start_note": built.start_note,  # the greeting cue, with when they last talked
        # buttons for the end screen: the game homework the tutor will suggest
        "game_homework": homework_buttons(plan, patient_id_for(user), settings),
        "voice": {"tap_to_talk": voice.tap_to_talk, "noise_level": voice.noise_level,
                  "record_audio": audio.enabled and voice.record_audio},
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


@app.post("/api/session/{session_id}/audio")
async def upload_audio(
    session_id: str,
    request: Request,
    user: User = Depends(verify_user),
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
    audio=Depends(get_audio_store),
) -> dict:
    """The session's recording (both voices), uploaded by the browser when it ends (09). Only
    for the account's own session, only while recording is on, at most once per session."""
    pid = patient_id_for(user)
    session = store.get_session(pid, session_id)
    if session is None or session.get("user_email") != user.email:
        raise HTTPException(status_code=404, detail="Session not found")
    if not (audio.enabled and voice_settings(store, settings, pid).record_audio):
        raise HTTPException(status_code=409, detail="Recording is off for this account")
    if session.get("audio_uri"):
        raise HTTPException(status_code=409, detail="This session already has a recording")
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type not in AUDIO_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported audio type")
    data = await request.body()
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Recording is empty or too large")
    uri = audio.save(pid, session_id, data, content_type, started_at=session.get("started_at"))
    store.update_session(pid, session_id, {"audio_uri": uri, "audio_bytes": len(data), "audio_type": content_type})
    print(f"[audio] saved {pid}/{session_id}: {len(data) // 1024} KB {content_type}", flush=True)
    return {"ok": True, "bytes": len(data)}


@app.post("/api/session/{session_id}/end")
def end_session(
    session_id: str,
    body: EndRequest,
    user: User = Depends(verify_user),
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
    profile: PatientProfileLoader = Depends(get_profile_loader),
    llm_client=Depends(get_text_client),
    games_reader=Depends(get_games_reader),
) -> dict:
    pid = patient_id_for(user)
    _own_active_session(store, settings, user, session_id)
    store.end_session(pid, session_id, body.reason)
    # Update the tutor's memory now, inside this request (Cloud Run throttles CPU after the
    # response). The browser doesn't wait: it sent this with keepalive and moved on.
    # Failures are recorded and retried by the hourly sweep.
    if billing_guard.is_paused(store):
        # Soft stop (10): the transcript is saved; the memory update waits ("pending") for the
        # sweep after a caregiver resumes.
        return {"status": "ended", "memory_status": "pending", "plan_status": None, "paused": True}
    bounded = _bounded_generate(settings.memory_end_deadline_s)  # one budget for both calls
    profile_text = profile.get()
    memory_status = run_memory_update(
        store, llm_client, settings, pid, session_id, profile_text=profile_text, generate_fn=bounded,
    )
    # Voice settings for next time, from this session's interruptions (09; code, no model).
    adjust_after_session(store, settings, pid, session_id)
    plan_status = None
    if memory_status == MEM_DONE:
        # The next session's lesson plan, built from the memory we just updated (05).
        plan_status = build_next_plan(
            store, llm_client, settings, pid, session_id, profile_text=profile_text, generate_fn=bounded,
            games=games_for(pid, settings, games_reader),
        )
    return {"status": "ended", "memory_status": memory_status, "plan_status": plan_status}


@app.get("/api/push/public-key")
def push_public_key(_user: User = Depends(verify_user), settings: Settings = Depends(get_settings)) -> dict:
    """The (public) key the browser needs to turn the daily reminder on (11)."""
    return {"key": settings.vapid_public_key}


@app.put("/api/reminder")
def set_my_reminder(
    enabled: bool = Body(..., embed=True),
    hour: int | None = Body(default=None, embed=True, ge=0, le=23),
    user: User = Depends(verify_user),
    store: SessionStore = Depends(get_store),
) -> dict:
    """From his own start screen (11): turn the daily reminder on/off and pick the hour. The
    chosen days stay as the caregiver set them."""
    current = ReminderSettings(**(store.get_reminder_settings(user.email) or {}))
    updated = current.model_copy(update={"enabled": enabled, **({"hour": hour} if hour is not None else {})})
    store.save_reminder_settings(user.email, updated.model_dump())
    return updated.model_dump()


@app.post("/api/push/subscribe")
def push_subscribe(
    subscription: dict = Body(..., embed=True),
    user: User = Depends(verify_user),
    store: SessionStore = Depends(get_store),
) -> dict:
    """This device wants the daily reminder: store its push subscription under the account (11)."""
    endpoint, keys = subscription.get("endpoint"), subscription.get("keys") or {}
    if not (isinstance(endpoint, str) and endpoint.startswith("https://") and keys.get("p256dh") and keys.get("auth")):
        raise HTTPException(status_code=422, detail="Not a push subscription")
    sub = {"endpoint": endpoint, "keys": {"p256dh": str(keys["p256dh"]), "auth": str(keys["auth"])}}
    store.add_push_subscription(patient_id_for(user), subscription_id(sub), sub)
    return {"ok": True}


@app.post("/internal/budget")
async def budget_alert(
    request: Request,
    _caller: str = Depends(verify_sweeper),  # Pub/Sub push, signed as the sweeper's service account
    store: SessionStore = Depends(get_store),
) -> dict:
    """The monthly budget's notifications (Pub/Sub push): records the spend and applies the
    soft stop at 75% of the budget (10). The kill switch handles 100% on its own."""
    body = await request.json()
    try:
        data = base64.b64decode(body["message"]["data"]).decode("utf-8")
        notification = json.loads(data)
    except Exception as exc:  # noqa: BLE001 -- a malformed message must not be retried forever
        print(f"[billing] unreadable budget message: {exc!r:.150}", flush=True)
        return {"ok": False}
    state = billing_guard.handle_notification(store, notification)
    return {"ok": True, "paused": state.get("paused", False)}


@app.post("/internal/memory/sweep")
def memory_sweep(
    _caller: str = Depends(verify_sweeper),
    push_sender=Depends(get_push_sender),
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
    profile: PatientProfileLoader = Depends(get_profile_loader),
    llm_client=Depends(get_text_client),
    games_reader=Depends(get_games_reader),
) -> dict:
    """Hourly (Cloud Scheduler): update memory for sessions still waiting -- tabs closed
    mid-session, or updates that failed because the models were overloaded -- and rebuild
    next plans that are stale because he played the games after they were built (06)."""
    # The daily reminder (11) first: it runs even when paused (and then records "skipped").
    reminders = run_reminders(store, sorted(settings.allowed_email_set), push_sender) if push_sender else {}
    if billing_guard.is_paused(store):
        return {"processed": {}, "paused": True, "reminders": reminders}  # soft stop (10): nothing calls a model
    results: dict[str, str] = {}
    budget = settings.memory_sweep_batch
    profile_text = profile.get()
    for pid in store.list_patient_ids():
        for sid in store.pending_memory_sessions(pid, limit=budget - len(results)):
            results[sid] = run_memory_update(
                store, llm_client, settings, pid, sid,
                profile_text=profile_text, generate_fn=_bounded_generate(240),
            )
            adjust_after_session(store, settings, pid, sid)  # once per session (09)
        # Plans that are missing (memory done, plan failed or never built): newest only --
        # a plan always reflects the latest memory, so one per account is enough.
        games = games_for(pid, settings, games_reader)
        for sid in store.pending_plan_sessions(pid, limit=1):
            if len(results) >= budget:
                break
            status = build_next_plan(
                store, llm_client, settings, pid, sid,
                profile_text=profile_text, generate_fn=_bounded_generate(180), games=games,
            )
            results[f"plan:{sid}"] = status
        # Stale plan: he played after it was built -> rebuild it with the fresh games data.
        next_plan = store.get_next_plan(pid)
        played = games.latest_played if games and not games.error else None
        built_at = next_plan.get("built_at") if next_plan else None
        if (played and built_at and played > built_at and len(results) < budget
                and next_plan.get("built_after_session")):
            sid = next_plan["built_after_session"]
            results[f"replan:{sid}"] = build_next_plan(
                store, llm_client, settings, pid, sid,
                profile_text=profile_text, generate_fn=_bounded_generate(180), games=games,
            )
        if len(results) >= budget:
            break
    return {"processed": results, "reminders": reminders}


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


# ---- caregiver page (08): every allowlisted account, caregivers only ------------------------

@app.get("/caregiver", response_class=HTMLResponse)
@app.get("/caregiver.html", response_class=HTMLResponse)
def caregiver_page() -> str:
    # The page itself is public (like index.html); all of its data comes from
    # /api/caregiver/*, which requires a caregiver sign-in.
    html = (STATIC_DIR / "caregiver.html").read_text(encoding="utf-8")
    return html.replace("__ASSET_VERSION__", asset_version())


app.include_router(caregiver_router)


# Mounted last so API routes take precedence over static files.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
