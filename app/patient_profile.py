"""Loads the private, de-identified patient profile that personalizes the tutor prompt.

The profile never lives in git or the container image (the repo is public). Its home is
a private Cloud Storage object (PATIENT_PROFILE_URI=gs://...), readable only by the app's
service account. For local development without the bucket, a gitignored local file
(PATIENT_PROFILE_PATH) is used instead.
"""

import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from app.config import Settings
from app.prompts import read_optional_text

CACHE_TTL_S = 300  # a profile edit (re-upload) reaches the tutor within 5 minutes
VOCABULARY_PREFIX = "vocabulary:"


def extract_vocabulary(profile: str) -> list[str]:
    """Names/places listed on 'Vocabulary: a, b, c' lines of the profile.

    They bias Gemini's transcription toward his proper nouns -- exactly the words his
    therapist says he struggles to retrieve, and the ones speech recognition gets wrong.
    """
    words: list[str] = []
    for line in profile.splitlines():
        stripped = line.strip().lstrip("-* ").strip()
        if stripped.lower().startswith(VOCABULARY_PREFIX):
            items = stripped[len(VOCABULARY_PREFIX):].replace("،", ",").split(",")
            words += [w.strip() for w in items if w.strip()]
    return list(dict.fromkeys(words))  # de-duplicate, keep order


def _log(message: str) -> None:
    print(f"[patient_profile] {message}", file=sys.stderr, flush=True)


def read_gcs_text(uri: str) -> str:
    from google.cloud import storage  # imported lazily: only needed when a URI is configured

    bucket_name, _, blob_name = uri.removeprefix("gs://").partition("/")
    blob = storage.Client().bucket(bucket_name).blob(blob_name)
    return blob.download_as_text(encoding="utf-8").strip()


class PatientProfileLoader:
    def __init__(
        self,
        settings: Settings,
        read_gcs: Callable[[str], str] = read_gcs_text,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._uri = settings.patient_profile_uri
        self._path: Path | None = settings.patient_profile_path
        self._read_gcs = read_gcs
        self._clock = clock
        self._cached: str | None = None
        self._cached_at = 0.0
        self._lock = threading.Lock()

    def get(self) -> str:
        if not self._uri:
            return read_optional_text(self._path)
        with self._lock:
            if self._cached is not None and self._clock() - self._cached_at < CACHE_TTL_S:
                return self._cached
            try:
                self._cached = self._read_gcs(self._uri)
                self._cached_at = self._clock()
            except Exception as exc:  # never block a session on this
                _log(f"could not read {self._uri}: {exc!r}")
                if self._cached is None:
                    return ""  # the tutor still works, just without personalization
            return self._cached
