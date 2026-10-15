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


# ---- the needs profile and the inferred profile (15.5) ---------------------------------------------
LEVELS = ("ok", "some_difficulty", "clear_difficulty", "unclear")
AREA_NAMES = {"conversation": "Conversation (fluency, word-finding in talk)", "naming": "Naming",
              "repetition": "Repetition", "understanding": "Understanding",
              "connected_speech": "Connected speech (explaining, telling in order)",
              "clarity": "Speech clarity", "goals": "His goals"}
PRACTICED = ("conversation", "naming", "connected_speech")  # what the app can practice today
MAX_HISTORY = 30  # levels kept per area, one per session that showed it
MAX_POINTS = 30  # points for his therapist kept (newest)
MAX_ABOUT, MAX_ABOUT_CHARS = 8, 160
MAX_VOCABULARY, MAX_VOCABULARY_CHARS = 40, 40


def needs_lines(needs: dict | None) -> list[str]:
    """One line per area: level (who set it) -- note. For the plan builder and the inferred profile."""
    out = []
    for area, name in AREA_NAMES.items():
        a = ((needs or {}).get("areas") or {}).get(area)
        if not a:
            continue
        if area == "goals":
            out.append(f"{name}: {a.get('note', '')}".strip())
            continue
        by = " (set by the family)" if a.get("set_by") == "family" else ""
        note = f" -- {a['note']}" if a.get("note") else ""
        practiced = "" if area in PRACTICED else " [not practiced in the app yet]"
        out.append(f"{name}: {a.get('level', 'unclear').replace('_', ' ')}{by}{note}{practiced}")
    return out


def render_inferred(about: list[str], vocabulary: list[str], needs: dict | None) -> str:
    """The inferred profile's text, by code (never free-written): the same shape as an uploaded one,
    so its Vocabulary line feeds the transcription the same way."""
    lines = ["Inferred by the app from his conversations (not a diagnosis; only what he said and how it went):"]
    lines += [f"- {a}" for a in about]
    need = needs_lines(needs)
    if need:
        lines.append("What he needs (from the first sessions):")
        lines += [f"- {n}" for n in need]
    if vocabulary:
        lines.append(f"- Vocabulary: {', '.join(vocabulary)}")
    return "\n".join(lines) if len(lines) > 1 else ""
