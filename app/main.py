"""FastAPI entrypoint: `uvicorn app.main:app`."""

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Hebrew Speech Rehab Tutor")


# Not /healthz: Cloud Run reserves paths ending in "z" and 404s them before they reach the app.
@app.get("/api/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    # Report only whether the key is present -- never its value.
    return {"status": "ok", "gemini_key_configured": bool(settings.gemini_api_key)}


# Mounted last so API routes take precedence over static files.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
