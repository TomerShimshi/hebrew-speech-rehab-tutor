"""Debug archive: the exact system prompt each session's tutor received.

Saved to the private bucket as gs://<bucket>/debug/prompts/<email>/<name>.md, where the name
reads like a session log: "2026-10-03_16-47_regular-discourse_PLYI39zF.md" (Israel time, the
plan type and goal, and the start of the session id to match it in Firestore). Best-effort: a failure here never blocks a session. The app's
service account can only CREATE objects in the bucket (no overwrite/delete), and a
lifecycle rule deletes these files after 30 days (see deploy/setup_gcp.sh).
"""

import datetime as dt
import re
import sys
from collections.abc import Callable
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Jerusalem")  # file names in the family's local time

Uploader = Callable[[str, str], None]  # (gs:// uri, text) -> None


def _log(message: str) -> None:
    print(f"[prompt_archive] {message}", file=sys.stderr, flush=True)


def upload_to_gcs(uri: str, text: str) -> None:
    from google.cloud import storage  # lazy: only needed when archiving is configured

    bucket_name, _, blob_name = uri.removeprefix("gs://").partition("/")
    blob = storage.Client().bucket(bucket_name).blob(blob_name)
    blob.upload_from_string(text, content_type="text/markdown; charset=utf-8")


def archive_name(sid: str, label: str = "", now: dt.datetime | None = None) -> str:
    """e.g. 2026-10-03_16-47_regular-discourse_PLYI39zF.md (sorts chronologically)."""
    stamp = (now or dt.datetime.now(dt.timezone.utc)).astimezone(LOCAL_TZ).strftime("%Y-%m-%d_%H-%M")
    safe_label = re.sub(r"[^A-Za-z0-9_-]+", "-", label).strip("-")
    return "_".join(part for part in (stamp, safe_label, sid[:8]) if part) + ".md"


class PromptArchive:
    def __init__(self, prefix: str | None, upload: Uploader = upload_to_gcs):
        self._prefix = (prefix or "").rstrip("/")
        self._upload = upload

    def save_backup(self, *, pid: str, name: str, content: str) -> str | None:
        """A JSON backup next to the prompts (debug/memory-backups/...), same 30-day expiry."""
        if not self._prefix:
            return None
        base = self._prefix.rsplit("/", 1)[0]  # .../debug/prompts -> .../debug
        uri = f"{base}/memory-backups/{pid}/{name}"
        try:
            self._upload(uri, content)
            return uri
        except Exception as exc:  # noqa: BLE001
            _log(f"could not save {uri}: {exc!r:.200}")
            return None

    def save(self, *, pid: str, sid: str, prompt_text: str, meta: dict, label: str = "",
             now: dt.datetime | None = None) -> str | None:
        """Returns the gs:// uri, or None if archiving is off or failed."""
        if not self._prefix:
            return None
        uri = f"{self._prefix}/{pid}/{archive_name(sid, label, now)}"
        header = "\n".join(f"- **{k}:** {v}" for k, v in meta.items())
        body = (
            f"# Tutor prompt for session {sid}\n\n{header}\n"
            f"- **saved_at:** {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}\n\n"
            f"---\n\n{prompt_text}\n"
        )
        try:
            self._upload(uri, body)
            return uri
        except Exception as exc:  # noqa: BLE001 -- debugging aid only
            _log(f"could not save {uri}: {exc!r:.200}")
            return None
