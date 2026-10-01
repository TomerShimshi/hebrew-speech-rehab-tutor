"""Session + transcript storage: Firestore in production, in-memory for tests.

Layout (see docs/plans/03):
  patients/{pid}
  patients/{pid}/sessions/{sid}           status, timestamps, end_reason, prompt_version...
  patients/{pid}/sessions/{sid}/turns/{seq:05d}
"""

import datetime as dt
import uuid
from typing import Protocol

from app.transcripts import EndReason, TurnIn, turn_doc_id

ACTIVE = "active"
ENDED = "ended"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class SessionStore(Protocol):
    def create_session(self, pid: str, *, user_email: str, model: str, prompt_version: str) -> str: ...
    def get_session(self, pid: str, sid: str) -> dict | None: ...
    def upsert_turns(self, pid: str, sid: str, turns: list[TurnIn]) -> None: ...
    def end_session(self, pid: str, sid: str, reason: EndReason) -> None: ...
    def mark_abandoned(self, pid: str) -> int: ...
    def list_turns(self, pid: str, sid: str) -> list[dict]: ...


def _turn_fields(turn: TurnIn) -> dict:
    return {**turn.model_dump(mode="json"), "updated_at": _now()}


class InMemorySessionStore:
    def __init__(self) -> None:
        self.sessions: dict[tuple[str, str], dict] = {}
        self.turns: dict[tuple[str, str], dict[str, dict]] = {}

    def create_session(self, pid, *, user_email, model, prompt_version):
        sid = uuid.uuid4().hex
        self.sessions[(pid, sid)] = {
            "id": sid, "status": ACTIVE, "started_at": _now(), "ended_at": None,
            "end_reason": None, "user_email": user_email, "model": model,
            "prompt_version": prompt_version, "turn_count": 0,
        }
        self.turns[(pid, sid)] = {}
        return sid

    def get_session(self, pid, sid):
        return self.sessions.get((pid, sid))

    def upsert_turns(self, pid, sid, turns):
        docs = self.turns[(pid, sid)]
        for turn in turns:
            docs[turn_doc_id(turn.seq)] = _turn_fields(turn)

    def end_session(self, pid, sid, reason):
        self.sessions[(pid, sid)].update(
            status=ENDED, ended_at=_now(), end_reason=reason.value,
            turn_count=len(self.turns[(pid, sid)]),
        )

    def mark_abandoned(self, pid):
        stale = [k for k, v in self.sessions.items() if k[0] == pid and v["status"] == ACTIVE]
        for key in stale:
            self.sessions[key].update(
                status=ENDED, ended_at=_now(), end_reason=EndReason.abandoned.value
            )
        return len(stale)

    def list_turns(self, pid, sid):
        return [self.turns[(pid, sid)][k] for k in sorted(self.turns[(pid, sid)])]


class FirestoreSessionStore:
    def __init__(self, client=None) -> None:
        from google.cloud import firestore  # lazy: tests never import the client

        self._fs = firestore
        self._db = client or firestore.Client()

    def _patient(self, pid):
        return self._db.collection("patients").document(pid)

    def _session(self, pid, sid):
        return self._patient(pid).collection("sessions").document(sid)

    def create_session(self, pid, *, user_email, model, prompt_version):
        self._patient(pid).set({"created_at": self._fs.SERVER_TIMESTAMP}, merge=True)
        ref = self._patient(pid).collection("sessions").document()
        ref.set({
            "status": ACTIVE, "started_at": self._fs.SERVER_TIMESTAMP, "ended_at": None,
            "end_reason": None, "user_email": user_email, "model": model,
            "prompt_version": prompt_version, "turn_count": 0,
        })
        return ref.id

    def get_session(self, pid, sid):
        snap = self._session(pid, sid).get()
        return {"id": snap.id, **snap.to_dict()} if snap.exists else None

    def upsert_turns(self, pid, sid, turns):
        if not turns:
            return
        session = self._session(pid, sid)
        batch = self._db.batch()
        for turn in turns:
            batch.set(session.collection("turns").document(turn_doc_id(turn.seq)), _turn_fields(turn))
        batch.commit()

    def end_session(self, pid, sid, reason):
        session = self._session(pid, sid)
        # Counted once at the end (1 cheap aggregation read) -- exact even if flushes raced.
        count = int(session.collection("turns").count().get()[0][0].value)
        session.update({
            "status": ENDED, "ended_at": self._fs.SERVER_TIMESTAMP, "end_reason": reason.value,
            "turn_count": count,
        })

    def mark_abandoned(self, pid):
        sessions = self._patient(pid).collection("sessions")
        stale = list(sessions.where(filter=self._fs.FieldFilter("status", "==", ACTIVE)).stream())
        for snap in stale:
            snap.reference.update({
                "status": ENDED, "ended_at": self._fs.SERVER_TIMESTAMP,
                "end_reason": EndReason.abandoned.value,
            })
        return len(stale)

    def list_turns(self, pid, sid):
        turns = self._session(pid, sid).collection("turns").order_by("seq").stream()
        return [snap.to_dict() for snap in turns]
