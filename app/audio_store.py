"""Session audio recordings (sub-plan 09), for the caregiver page only.

The browser records both voices (his mic + her speech) and uploads the file when the session
ends. It's stored in the private bucket as gs://<bucket>/audio/<email>/<name>.<ext>, named by
the session's start in Israel time, like the prompt archive -- "2026-10-07_10-37_t9OAQMT1.webm"
(the end of the name is the session id's start, to match it in Firestore). A lifecycle rule
deletes it after 90 days. The app's service account can create objects but not
overwrite or delete them, so each session has at most one recording. Reading it back
(caregivers only) uses the read access the app already has for the patient profile.
"""

import datetime as dt
import sys

from app.prompt_archive import LOCAL_TZ

AUDIO_TYPES = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a"}  # Chrome/Firefox, Safari
MAX_AUDIO_BYTES = 15 * 1024 * 1024  # a 15-minute session is ~2-4 MB


def _log(message: str) -> None:
    print(f"[audio] {message}", file=sys.stderr, flush=True)


def recording_name(sid: str, content_type: str, started_at: dt.datetime | None) -> str:
    """e.g. 2026-10-07_10-37_t9OAQMT1.webm -- the session's start in Israel time (sorts by date)."""
    stamp = (started_at or dt.datetime.now(dt.timezone.utc)).astimezone(LOCAL_TZ).strftime("%Y-%m-%d_%H-%M")
    return f"{stamp}_{sid[:8]}.{AUDIO_TYPES[content_type]}"


class GcsAudioStore:
    def __init__(self, prefix: str):
        self._prefix = prefix.rstrip("/")  # e.g. gs://heb-practice-private/audio

    @property
    def enabled(self) -> bool:
        return bool(self._prefix)

    def _bucket_and_base(self):
        from google.cloud import storage  # lazy: tests never import the client
        bucket_name, _, base = self._prefix.removeprefix("gs://").partition("/")
        return storage.Client().bucket(bucket_name), base

    def save(self, pid: str, sid: str, data: bytes, content_type: str, started_at=None) -> str:
        bucket, base = self._bucket_and_base()
        name = recording_name(sid, content_type, started_at)
        bucket.blob(f"{base}/{pid}/{name}").upload_from_string(data, content_type=content_type, if_generation_match=0)
        return f"{self._prefix}/{pid}/{name}"

    def load(self, uri: str) -> bytes:
        bucket, base = self._bucket_and_base()
        name = uri.removeprefix(f"{self._prefix}/")
        return bucket.blob(f"{base}/{name}").download_as_bytes()

    def usage(self, pid: str) -> dict:
        """How much this account's recordings take (files still stored, before the 90-day expiry)."""
        bucket, base = self._bucket_and_base()
        blobs = list(bucket.list_blobs(prefix=f"{base}/{pid}/"))
        return {"files": len(blobs), "bytes": sum(b.size or 0 for b in blobs)}


class InMemoryAudioStore:
    """For tests and local runs without a bucket."""

    def __init__(self, prefix: str = "mem://audio"):
        self._prefix = prefix
        self.files: dict[str, tuple[bytes, str]] = {}

    @property
    def enabled(self) -> bool:
        return True

    def save(self, pid, sid, data, content_type, started_at=None):
        uri = f"{self._prefix}/{pid}/{recording_name(sid, content_type, started_at)}"
        if uri in self.files:
            raise FileExistsError(uri)  # like the bucket: create-only
        self.files[uri] = (data, content_type)
        return uri

    def load(self, uri):
        return self.files[uri][0]

    def usage(self, pid):
        mine = [d for u, (d, _) in self.files.items() if u.startswith(f"{self._prefix}/{pid}/")]
        return {"files": len(mine), "bytes": sum(len(d) for d in mine)}
