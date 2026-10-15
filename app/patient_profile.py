"""The profile that personalizes the tutor prompt -- one per account (15).

Kept with the account's data (Firestore, private, like its memory), never in git or the image
(the repo is public). Two sources:
- "uploaded": written by the family on the caregiver page (e.g. from his speech-language
  assessment). The app never overwrites it.
- "inferred": written by the app from his first sessions (15.5).
An account with neither has no profile. Nothing of one account's profile reaches another.
"""

import sys
from dataclasses import dataclass

PROFILE_MAX_CHARS = 8000  # a page or two: it goes into every prompt
SOURCES = ("uploaded", "inferred")
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


@dataclass(frozen=True)
class AccountProfile:
    text: str
    source: str  # "uploaded" | "inferred" | "" (none yet)


def account_profile(store, pid: str) -> AccountProfile:
    """This account's own profile, for the tutor and the agents. Never someone else's."""
    doc = store.get_profile(pid) or {}
    text = (doc.get("text") or "").strip()
    return AccountProfile(text, doc.get("source", "") if text else "")
