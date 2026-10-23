"""Session audio recordings (sub-plan 09), for the caregiver page only.

The browser records both voices (his mic + her speech) and uploads it IN PARTS while the session
runs -- a ~10-second piece at a time -- and the parts are joined into one file when it ends (or by the
hourly sweep, if the app was closed first). 23.10: one large upload after the end was lost when the
app closed right away (2 of the patient's 16 recordings). The parts are kept under
audio/<email>/parts/<session>/ (deleted with the rest after 90 days). It's stored in the private bucket as gs://<bucket>/audio/<email>/<name>.<ext>, named by
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
MAX_PART_BYTES = 2 * 1024 * 1024  # a ~10-second piece is ~30 KB
MAX_PARTS = 400
COMPOSE_MAX = 32  # Cloud Storage joins at most 32 objects per call


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

    def _part_prefix(self, base: str, pid: str, sid: str) -> str:
        return f"{base}/{pid}/parts/{sid}/"

    def save_part(self, pid: str, sid: str, n: int, data: bytes, content_type: str) -> bool:
        """One piece, create-only; a piece sent twice (a retry) is simply already there."""
        from google.api_core.exceptions import PreconditionFailed
        bucket, base = self._bucket_and_base()
        blob = bucket.blob(f"{self._part_prefix(base, pid, sid)}{n:04d}.{AUDIO_TYPES[content_type]}")
        try:
            blob.upload_from_string(data, content_type=content_type, if_generation_match=0)
            return True
        except PreconditionFailed:
            return False

    def part_count(self, pid: str, sid: str) -> int:
        bucket, base = self._bucket_and_base()
        return sum(1 for b in bucket.list_blobs(prefix=self._part_prefix(base, pid, sid)) if "/c" not in b.name[-12:])

    def join_parts(self, pid: str, sid: str, content_type: str, started_at=None) -> tuple[str, int, int] | None:
        """The parts, in order, joined into the session's recording (in stages of 32). Returns
        (uri, bytes, parts) or None when there are none. Pieces from one recorder join into a valid file."""
        bucket, base = self._bucket_and_base()
        prefix = self._part_prefix(base, pid, sid)
        parts = sorted((b for b in bucket.list_blobs(prefix=prefix) if b.name[len(prefix):][:1].isdigit()),
                       key=lambda b: b.name)
        if not parts:
            return None
        sources, stage = parts, 0
        while len(sources) > COMPOSE_MAX:
            joined = []
            for i in range(0, len(sources), COMPOSE_MAX):
                out = bucket.blob(f"{prefix}c{stage}-{i // COMPOSE_MAX:03d}")
                out.content_type = content_type
                out.compose(sources[i:i + COMPOSE_MAX])
                joined.append(out)
            sources, stage = joined, stage + 1
        name = recording_name(sid, content_type, started_at)
        final = bucket.blob(f"{base}/{pid}/{name}")
        final.content_type = content_type
        final.compose(sources, if_generation_match=0)
        final.reload()
        return f"{self._prefix}/{pid}/{name}", final.size or 0, len(parts)

    def load(self, uri: str) -> bytes:
        bucket, base = self._bucket_and_base()
        name = uri.removeprefix(f"{self._prefix}/")
        return bucket.blob(f"{base}/{name}").download_as_bytes()

    def usage(self, pid: str) -> dict:
        """How much this account's recordings take (files still stored, before the 90-day expiry)."""
        bucket, base = self._bucket_and_base()
        blobs = list(bucket.list_blobs(prefix=f"{base}/{pid}/"))
        files = [b for b in blobs if "/parts/" not in b.name]
        return {"files": len(files), "bytes": sum(b.size or 0 for b in files)}


class InMemoryAudioStore:
    """For tests and local runs without a bucket."""

    def __init__(self, prefix: str = "mem://audio"):
        self._prefix = prefix
        self.files: dict[str, tuple[bytes, str]] = {}
        self.parts: dict[tuple[str, str], dict[int, tuple[bytes, str]]] = {}

    @property
    def enabled(self) -> bool:
        return True

    def save(self, pid, sid, data, content_type, started_at=None):
        uri = f"{self._prefix}/{pid}/{recording_name(sid, content_type, started_at)}"
        if uri in self.files:
            raise FileExistsError(uri)  # like the bucket: create-only
        self.files[uri] = (data, content_type)
        return uri

    def save_part(self, pid, sid, n, data, content_type):
        key = (pid, sid)
        parts = self.parts.setdefault(key, {})
        if n in parts:
            return False
        parts[n] = (data, content_type)
        return True

    def part_count(self, pid, sid):
        return len(self.parts.get((pid, sid), {}))

    def join_parts(self, pid, sid, content_type, started_at=None):
        parts = self.parts.get((pid, sid))
        if not parts:
            return None
        data = b"".join(parts[n][0] for n in sorted(parts))
        return self.save(pid, sid, data, content_type, started_at), len(data), len(parts)

    def load(self, uri):
        return self.files[uri][0]

    def usage(self, pid):
        mine = [d for u, (d, _) in self.files.items() if u.startswith(f"{self._prefix}/{pid}/")]
        return {"files": len(mine), "bytes": sum(len(d) for d in mine)}
