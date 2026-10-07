"""Shared FastAPI dependencies (used by main.py and the caregiver router).

Tests replace them through app.dependency_overrides, so every route must use these exact
function objects.
"""

import time
from functools import lru_cache

from fastapi import Depends, HTTPException

from app.config import Settings, get_settings
from app.games import UpstashReader, games_snapshot, profile_for
from app.llm import generate, text_client
from app.patient_profile import PatientProfileLoader
from app.audio_store import GcsAudioStore
from app.prompt_archive import PromptArchive
from app.store import FirestoreSessionStore, SessionStore


@lru_cache
def get_store() -> SessionStore:
    return FirestoreSessionStore()


@lru_cache
def get_prompt_archive() -> PromptArchive:
    return PromptArchive(get_settings().prompt_archive_uri)


@lru_cache
def get_audio_store():
    return GcsAudioStore(get_settings().audio_uri_prefix)


def get_push_sender(settings: Settings = Depends(get_settings)):
    """Sends Web Push notifications (11), or None when the keys aren't configured."""
    if not (settings.vapid_private_key and settings.vapid_public_key):
        return None
    from app.reminders import webpush_sender
    return webpush_sender(settings.vapid_private_key, settings.sweep_audience or "https://localhost")


@lru_cache
def get_profile_loader() -> PatientProfileLoader:
    return PatientProfileLoader(get_settings())


@lru_cache
def get_games_reader():
    s = get_settings()
    if not (s.upstash_redis_rest_url and s.upstash_redis_readonly_token):
        return None  # games integration not configured: everything else works as before
    return UpstashReader(s.upstash_redis_rest_url, s.upstash_redis_readonly_token)


def games_for(pid: str, settings: Settings, reader):
    """His Simon games snapshot (read-only), or None if this account has no games profile."""
    profile_name = profile_for(pid, settings.simon_profiles)
    if reader is None or not profile_name:
        return None
    return games_snapshot(reader, profile_name)


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
