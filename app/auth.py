"""Google sign-in (Firebase Auth) verification + email allowlist.

The browser signs in with Firebase and sends its ID token as `Authorization: Bearer ...`.
We verify it with google-auth (signature, expiry, audience = our project) -- no
firebase-admin needed -- then require a verified email on the allowlist.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, HTTPException, Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.config import Settings, get_settings

TokenVerifier = Callable[[str, str], dict]  # (token, project_id) -> claims


@dataclass(frozen=True)
class User:
    uid: str
    email: str


@lru_cache
def _transport() -> google_requests.Request:
    # Caches Google's public signing certs between requests.
    return google_requests.Request()


def verify_with_google(token: str, project_id: str) -> dict:
    return id_token.verify_firebase_token(token, _transport(), audience=project_id)


def get_token_verifier() -> TokenVerifier:
    return verify_with_google


def verify_user(
    request: Request,
    settings: Settings = Depends(get_settings),
    verify: TokenVerifier = Depends(get_token_verifier),
) -> User:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Sign-in required")
    try:
        claims = verify(token, settings.gcp_project_id)
    except Exception:  # bad signature, expired, wrong audience, malformed...
        raise HTTPException(status_code=401, detail="Invalid or expired sign-in")
    email = str(claims.get("email", "")).lower()
    if not email or not claims.get("email_verified"):
        raise HTTPException(status_code=403, detail="A verified Google email is required")
    if email not in settings.allowed_email_set:
        raise HTTPException(status_code=403, detail="This account is not allowed")
    return User(uid=str(claims.get("user_id") or claims.get("sub") or ""), email=email)


def require_caregiver(
    user: User = Depends(verify_user), settings: Settings = Depends(get_settings)
) -> User:
    if user.email not in settings.caregiver_email_set:
        raise HTTPException(status_code=403, detail="Caregiver access only")
    return user
