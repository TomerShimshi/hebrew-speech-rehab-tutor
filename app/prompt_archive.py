"""Debug archive: the exact system prompt each session's tutor received.

Saved to the private bucket as gs://<bucket>/debug/prompts/<email>/<session id>.md (readable in
the Cloud Storage console). Best-effort: a failure here never blocks a session. The app's
service account can only CREATE objects in the bucket (no overwrite/delete), and a
lifecycle rule deletes these files after 30 days (see deploy/setup_gcp.sh).
"""

import datetime as dt
import sys
from collections.abc import Callable

Uploader = Callable[[str, str], None]  # (gs:// uri, text) -> None


def _log(message: str) -> None:
    print(f"[prompt_archive] {message}", file=sys.stderr, flush=True)


def upload_to_gcs(uri: str, text: str) -> None:
    from google.cloud import storage  # lazy: only needed when archiving is configured

    bucket_name, _, blob_name = uri.removeprefix("gs://").partition("/")
    blob = storage.Client().bucket(bucket_name).blob(blob_name)
    blob.upload_from_string(text, content_type="text/markdown; charset=utf-8")


class PromptArchive:
    def __init__(self, prefix: str | None, upload: Uploader = upload_to_gcs):
        self._prefix = (prefix or "").rstrip("/")
        self._upload = upload

    def save(self, *, pid: str, sid: str, prompt_text: str, meta: dict) -> str | None:
        """Returns the gs:// uri, or None if archiving is off or failed."""
        if not self._prefix:
            return None
        uri = f"{self._prefix}/{pid}/{sid}.md"
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
