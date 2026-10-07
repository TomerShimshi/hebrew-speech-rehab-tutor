"""Session + transcript storage: Firestore in production, in-memory for tests.

Layout (see docs/plans/03 and 04):
  patients/{pid}
  patients/{pid}/sessions/{sid}           status, timestamps, end_reason, memory_status, summary...
  patients/{pid}/sessions/{sid}/turns/{seq:05d}
  patients/{pid}/memory/current           the tutor's long-term memory of him (MemoryDoc)
  patients/{pid}/memory_history/{sid}     the previous memory, saved before each update
  patients/{pid}/flags/{id}               things the family should see
  patients/{pid}/plans/next               the lesson plan for the coming session (05)
  patients/{pid}/technique_notes/{id}     research findings, keyed by the normalized question (07)
  patients/{pid}/research_usage/{date}    research runs that day (07)
  usage/{provider}-{YYYY-MM}              app-wide searches that month: tavily (07), gemini (10)
  usage/billing                           the month's spend and the soft stop (10)
  patients/{pid}/push_subscriptions/{id}  devices that turned the daily reminder on (11)
  patients/{pid}/reminders/{date}         that day's reminder: sent / skipped and why (11)
  patients/{pid}/caregiver/reminder       reminder settings: on/off, hour, days (11)
  patients/{pid}/caregiver/notes          the caregiver's notes for the plan builder (08)
  patients/{pid}/caregiver/settings       per-account session settings: voice, tap-to-talk (09)
  patients/{pid}/sessions/{sid}/prompt/live  the exact system instruction the tutor got (8.5)
"""

import datetime as dt
import uuid
from typing import Protocol

from app.transcripts import EndReason, TurnIn, turn_doc_id

ACTIVE = "active"
ENDED = "ended"


def recommendation_id(rec: dict) -> str:
    """De-duplication key: the same game + kind + title is one recommendation."""
    import hashlib
    raw = f"{rec.get('game_id')}|{rec.get('kind')}|{' '.join(str(rec.get('title', '')).lower().split())}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

# memory_status of an ended session (sub-plan 04)
MEM_PENDING, MEM_PROCESSING, MEM_DONE, MEM_FAILED, MEM_SKIPPED = (
    "pending", "processing", "done", "failed", "skipped")
STALE_PROCESSING = dt.timedelta(minutes=10)

# plan_status of a session whose memory is done (sub-plan 05)
PLAN_PENDING, PLAN_DONE, PLAN_FAILED = "pending", "done", "failed"  # a crashed update is retried after this
MAX_PLAN_ATTEMPTS = 3  # automatic plan builds per session; then the sweep stops (quota) -- "rebuild" still works


def _claimable(session: dict, now: dt.datetime) -> bool:
    status = session.get("memory_status")
    if session.get("status") != ENDED:
        return False
    if status in (MEM_PENDING, MEM_FAILED):
        return True
    claimed_at = session.get("memory_claimed_at")
    return status == MEM_PROCESSING and (claimed_at is None or now - claimed_at > STALE_PROCESSING)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class SessionStore(Protocol):
    def create_session(self, pid: str, *, user_email: str, model: str, prompt_version: str) -> str: ...
    def get_session(self, pid: str, sid: str) -> dict | None: ...
    def upsert_turns(self, pid: str, sid: str, turns: list[TurnIn]) -> None: ...
    def end_session(self, pid: str, sid: str, reason: EndReason) -> None: ...
    def mark_abandoned(self, pid: str) -> int: ...
    def list_turns(self, pid: str, sid: str) -> list[dict]: ...
    # memory (sub-plan 04)
    def update_session(self, pid: str, sid: str, fields: dict) -> None: ...
    def claim_for_memory(self, pid: str, sid: str) -> bool: ...
    def pending_memory_sessions(self, pid: str, limit: int = 2) -> list[str]: ...
    def get_memory(self, pid: str) -> dict | None: ...
    def save_memory(self, pid: str, sid: str, memory: dict, previous: dict | None) -> None: ...
    def add_flag(self, pid: str, sid: str, flag: dict) -> None: ...
    def list_patient_ids(self) -> list[str]: ...
    # caregiver resets (forget memory / delete everything)
    def account_overview(self, pid: str) -> dict: ...
    def forget_memory(self, pid: str) -> None: ...
    def delete_account(self, pid: str) -> int: ...
    # lesson plans (sub-plan 05)
    def get_next_plan(self, pid: str) -> dict | None: ...
    def save_next_plan(self, pid: str, sid: str, plan: dict) -> None: ...
    def recent_session_plans(self, pid: str, n: int = 5) -> list[dict]: ...
    def pending_plan_sessions(self, pid: str, limit: int = 2) -> list[str]: ...
    # games-app recommendations (sub-plan 06)
    def add_games_recommendation(self, pid: str, sid: str, rec: dict) -> None: ...
    # research (sub-plan 07)
    def get_technique_note(self, pid: str, note_id: str) -> dict | None: ...
    def save_technique_note(self, pid: str, note_id: str, note: dict) -> None: ...
    def recent_technique_notes(self, pid: str, n: int = 3) -> list[dict]: ...
    def research_runs_on(self, pid: str, day: str) -> int: ...
    def add_research_run(self, pid: str, day: str) -> None: ...
    def searches_in_month(self, month: str, provider: str = "tavily") -> int: ...
    def add_search(self, month: str, provider: str = "tavily") -> None: ...
    # caregiver page (sub-plan 08), newest first
    def list_sessions(self, pid: str, n: int = 30) -> list[dict]: ...
    def list_flags(self, pid: str, n: int = 50) -> list[dict]: ...
    def list_recommendations(self, pid: str) -> list[dict]: ...
    def list_memory_history(self, pid: str, n: int = 20) -> list[dict]: ...
    def get_memory_version(self, pid: str, version: str) -> dict | None: ...
    def resolve_flag(self, pid: str, flag_id: str, by: str) -> bool: ...
    def set_recommendation_status(self, pid: str, rec_id: str, status: str) -> bool: ...
    def get_notes(self, pid: str) -> dict | None: ...
    def save_notes(self, pid: str, text: str, by: str) -> None: ...
    def save_session_prompt(self, pid: str, sid: str, text: str, version: str) -> None: ...
    def get_settings(self, pid: str) -> dict | None: ...
    def get_billing_state(self) -> dict | None: ...
    def add_push_subscription(self, pid: str, sub_id: str, sub: dict) -> None: ...
    def list_push_subscriptions(self, pid: str) -> list[dict]: ...
    def remove_push_subscription(self, pid: str, sub_id: str) -> None: ...
    def get_reminder_settings(self, pid: str) -> dict | None: ...
    def save_reminder_settings(self, pid: str, settings: dict) -> None: ...
    def get_reminder(self, pid: str, doc_id: str) -> dict | None: ...
    def save_reminder(self, pid: str, doc_id: str, record: dict) -> None: ...
    def list_reminders(self, pid: str, n: int = 10) -> list[dict]: ...
    def set_billing_state(self, state: dict) -> None: ...
    def save_settings(self, pid: str, settings: dict, by: str) -> None: ...
    def get_session_prompt(self, pid: str, sid: str) -> dict | None: ...


def _turn_fields(turn: TurnIn) -> dict:
    return {**turn.model_dump(mode="json"), "updated_at": _now()}


class InMemorySessionStore:
    def __init__(self) -> None:
        self.sessions: dict[tuple[str, str], dict] = {}
        self.turns: dict[tuple[str, str], dict[str, dict]] = {}
        self.memory: dict[str, dict] = {}
        self.memory_history: dict[tuple[str, str], dict] = {}
        self.flags: list[dict] = []
        self.next_plans: dict[str, dict] = {}
        self.recommendations: dict[tuple[str, str], dict] = {}
        self.technique_notes: dict[tuple[str, str], dict] = {}
        self.research_runs: dict[tuple[str, str], int] = {}
        self.monthly_searches: dict[str, int] = {}
        self.notes: dict[str, dict] = {}
        self.session_prompts: dict[tuple[str, str], dict] = {}
        self.settings: dict[str, dict] = {}
        self.billing: dict | None = None
        self.push_subs: dict[tuple[str, str], dict] = {}
        self.reminder_settings: dict[str, dict] = {}
        self.reminders: dict[tuple[str, str], dict] = {}

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
            turn_count=len(self.turns[(pid, sid)]), memory_status=MEM_PENDING,
        )

    def mark_abandoned(self, pid):
        stale = [k for k, v in self.sessions.items() if k[0] == pid and v["status"] == ACTIVE]
        for key in stale:
            self.sessions[key].update(
                status=ENDED, ended_at=_now(), end_reason=EndReason.abandoned.value,
                turn_count=len(self.turns[key]), memory_status=MEM_PENDING,
            )
        return len(stale)

    def list_turns(self, pid, sid):
        return [self.turns[(pid, sid)][k] for k in sorted(self.turns[(pid, sid)])]

    def update_session(self, pid, sid, fields):
        self.sessions[(pid, sid)].update(fields)

    def claim_for_memory(self, pid, sid):
        session = self.sessions.get((pid, sid))
        if not session or not _claimable(session, _now()):
            return False
        session.update(memory_status=MEM_PROCESSING, memory_claimed_at=_now())
        return True

    def pending_memory_sessions(self, pid, limit=2):
        now = _now()
        found = [v for k, v in self.sessions.items() if k[0] == pid and _claimable(v, now)]
        found.sort(key=lambda v: v["started_at"])
        return [v["id"] for v in found[:limit]]

    def get_memory(self, pid):
        return self.memory.get(pid)

    def save_memory(self, pid, sid, memory, previous):
        if previous is not None:
            self.memory_history[(pid, sid)] = previous
        self.memory[pid] = {**memory, "updated_at": _now()}

    def add_flag(self, pid, sid, flag):
        self.flags.append({**flag, "id": uuid.uuid4().hex, "pid": pid, "session_id": sid,
                           "created_at": _now(), "status": "open"})

    def list_patient_ids(self):
        return sorted({pid for pid, _ in self.sessions} | set(self.memory))

    def account_overview(self, pid):
        memory = self.memory.get(pid) or {}
        return {
            "sessions": sum(1 for p, _ in self.sessions if p == pid),
            "has_memory": bool(memory.get("memory_prompt")),
            "sessions_processed": memory.get("sessions_processed", 0),
            "words": len(memory.get("word_bank", {})),
        }

    def forget_memory(self, pid):
        self.memory.pop(pid, None)
        self.next_plans.pop(pid, None)  # the next session is an intro again

    def delete_account(self, pid):
        keys = [k for k in self.sessions if k[0] == pid]
        for key in keys:
            self.sessions.pop(key)
            self.turns.pop(key, None)
        self.memory.pop(pid, None)
        self.next_plans.pop(pid, None)
        for key in [k for k in self.memory_history if k[0] == pid]:
            self.memory_history.pop(key)
        self.flags = [f for f in self.flags if f.get("pid") != pid]
        for store in (self.recommendations, self.technique_notes, self.research_runs):
            for key in [k for k in store if k[0] == pid]:
                store.pop(key)
        self.notes.pop(pid, None)
        self.settings.pop(pid, None)
        self.reminder_settings.pop(pid, None)
        for store in (self.push_subs, self.reminders):
            for key in [k for k in store if k[0] == pid]:
                store.pop(key)
        for key in [k for k in self.session_prompts if k[0] == pid]:
            self.session_prompts.pop(key)
        return len(keys)

    def get_next_plan(self, pid):
        return self.next_plans.get(pid)

    def save_next_plan(self, pid, sid, plan):
        self.next_plans[pid] = {**plan, "built_after_session": sid, "built_at": _now()}

    def recent_session_plans(self, pid, n=5):
        sessions = sorted((v for k, v in self.sessions.items() if k[0] == pid),
                          key=lambda v: v["started_at"], reverse=True)
        return [v["class_plan"] for v in sessions if v.get("class_plan")][:n]

    def add_games_recommendation(self, pid, sid, rec):
        key = (pid, recommendation_id(rec))
        if key in self.recommendations:
            r = self.recommendations[key]
            r.update(times_suggested=r["times_suggested"] + 1, last_session=sid, last_seen=_now())
        else:
            self.recommendations[key] = {**rec, "id": key[1], "status": "new", "times_suggested": 1,
                                         "first_session": sid, "last_session": sid, "last_seen": _now()}

    def get_technique_note(self, pid, note_id):
        return self.technique_notes.get((pid, note_id))

    def save_technique_note(self, pid, note_id, note):
        self.technique_notes[(pid, note_id)] = {**note, "created_at": _now()}

    def recent_technique_notes(self, pid, n=3):
        notes = [v for k, v in self.technique_notes.items() if k[0] == pid]
        return sorted(notes, key=lambda v: v["created_at"], reverse=True)[:n]

    def research_runs_on(self, pid, day):
        return self.research_runs.get((pid, day), 0)

    def list_sessions(self, pid, n=30):
        found = [v for k, v in self.sessions.items() if k[0] == pid]
        return sorted(found, key=lambda v: v["started_at"], reverse=True)[:n]

    def list_flags(self, pid, n=50):
        return sorted((f for f in self.flags if f.get("pid") == pid), key=lambda f: f["created_at"], reverse=True)[:n]

    def list_recommendations(self, pid):
        recs = [v for k, v in self.recommendations.items() if k[0] == pid]
        return sorted(recs, key=lambda v: v["last_seen"], reverse=True)

    def list_memory_history(self, pid, n=20):
        versions = [{**v, "version": k[1]} for k, v in self.memory_history.items() if k[0] == pid]
        return sorted(versions, key=lambda v: v.get("updated_at") or _now(), reverse=True)[:n]

    def get_memory_version(self, pid, version):
        return self.memory_history.get((pid, version))

    def resolve_flag(self, pid, flag_id, by):
        for f in self.flags:
            if f.get("pid") == pid and f.get("id") == flag_id:
                f.update(status="resolved", resolved_by=by, resolved_at=_now())
                return True
        return False

    def set_recommendation_status(self, pid, rec_id, status):
        rec = self.recommendations.get((pid, rec_id))
        if rec is None:
            return False
        rec.update(status=status, status_updated_at=_now())
        return True

    def get_notes(self, pid):
        return self.notes.get(pid)

    def save_notes(self, pid, text, by):
        self.notes[pid] = {"text": text, "updated_by": by, "updated_at": _now()}

    def save_session_prompt(self, pid, sid, text, version):
        self.session_prompts[(pid, sid)] = {"text": text, "prompt_version": version, "saved_at": _now()}

    def get_session_prompt(self, pid, sid):
        return self.session_prompts.get((pid, sid))

    def get_settings(self, pid):
        return self.settings.get(pid)

    def get_billing_state(self):
        return self.billing

    def set_billing_state(self, state):
        self.billing = dict(state)

    def add_push_subscription(self, pid, sub_id, sub):
        self.push_subs[(pid, sub_id)] = {**sub, "id": sub_id, "created_at": _now()}

    def list_push_subscriptions(self, pid):
        return [v for k, v in self.push_subs.items() if k[0] == pid]

    def remove_push_subscription(self, pid, sub_id):
        self.push_subs.pop((pid, sub_id), None)

    def get_reminder_settings(self, pid):
        return self.reminder_settings.get(pid)

    def save_reminder_settings(self, pid, settings):
        self.reminder_settings[pid] = dict(settings)

    def get_reminder(self, pid, doc_id):
        return self.reminders.get((pid, doc_id))

    def save_reminder(self, pid, doc_id, record):
        self.reminders[(pid, doc_id)] = {**record, "id": doc_id}

    def list_reminders(self, pid, n=10):
        mine = [v for k, v in self.reminders.items() if k[0] == pid]
        return sorted(mine, key=lambda v: v.get("at") or _now(), reverse=True)[:n]

    def save_settings(self, pid, settings, by):
        self.settings[pid] = {**settings, "updated_by": by, "updated_at": _now()}

    def add_research_run(self, pid, day):
        self.research_runs[(pid, day)] = self.research_runs_on(pid, day) + 1

    def searches_in_month(self, month, provider="tavily"):
        return self.monthly_searches.get(f"{provider}-{month}", 0)

    def add_search(self, month, provider="tavily"):
        self.monthly_searches[f"{provider}-{month}"] = self.searches_in_month(month, provider) + 1

    def pending_plan_sessions(self, pid, limit=2):
        found = [v for k, v in self.sessions.items()
                 if k[0] == pid and v.get("plan_status") in (PLAN_PENDING, PLAN_FAILED)
                 and v.get("plan_attempts", 0) < MAX_PLAN_ATTEMPTS]
        found.sort(key=lambda v: v["started_at"], reverse=True)
        return [v["id"] for v in found[:limit]]


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
            "turn_count": count, "memory_status": MEM_PENDING,
        })

    def mark_abandoned(self, pid):
        sessions = self._patient(pid).collection("sessions")
        stale = list(sessions.where(filter=self._fs.FieldFilter("status", "==", ACTIVE)).stream())
        for snap in stale:
            count = int(snap.reference.collection("turns").count().get()[0][0].value)
            snap.reference.update({
                "status": ENDED, "ended_at": self._fs.SERVER_TIMESTAMP,
                "end_reason": EndReason.abandoned.value, "turn_count": count,
                "memory_status": MEM_PENDING,
            })
        return len(stale)

    def list_turns(self, pid, sid):
        turns = self._session(pid, sid).collection("turns").order_by("seq").stream()
        return [snap.to_dict() for snap in turns]

    def update_session(self, pid, sid, fields):
        self._session(pid, sid).update(fields)

    def claim_for_memory(self, pid, sid):
        ref = self._session(pid, sid)
        fs = self._fs

        @fs.transactional
        def claim(transaction):
            snap = ref.get(transaction=transaction)
            if not snap.exists or not _claimable(snap.to_dict(), _now()):
                return False
            transaction.update(ref, {"memory_status": MEM_PROCESSING, "memory_claimed_at": _now()})
            return True

        return claim(self._db.transaction())

    def pending_memory_sessions(self, pid, limit=2):
        sessions = self._patient(pid).collection("sessions")
        query = sessions.where(filter=self._fs.FieldFilter(
            "memory_status", "in", [MEM_PENDING, MEM_FAILED, MEM_PROCESSING]))
        now = _now()
        found = [{"id": s.id, **s.to_dict()} for s in query.stream()]
        found = [s for s in found if _claimable(s, now)]
        found.sort(key=lambda s: s.get("started_at") or now)
        return [s["id"] for s in found[:limit]]

    def get_memory(self, pid):
        snap = self._patient(pid).collection("memory").document("current").get()
        return snap.to_dict() if snap.exists else None

    def save_memory(self, pid, sid, memory, previous):
        batch = self._db.batch()
        if previous is not None:
            batch.set(self._patient(pid).collection("memory_history").document(sid), previous)
        batch.set(self._patient(pid).collection("memory").document("current"),
                  {**memory, "updated_at": self._fs.SERVER_TIMESTAMP})
        batch.commit()

    def list_patient_ids(self):
        return [doc.id for doc in self._db.collection("patients").list_documents()]

    def account_overview(self, pid):
        memory = self.get_memory(pid) or {}
        sessions = self._patient(pid).collection("sessions").count().get()[0][0].value
        return {
            "sessions": int(sessions),
            "has_memory": bool(memory.get("memory_prompt")),
            "sessions_processed": memory.get("sessions_processed", 0),
            "words": len(memory.get("word_bank", {})),
        }

    def forget_memory(self, pid):
        # Only the live memory (and the plan built from it): transcripts, sessions and
        # memory_history are kept. The next session is an intro again.
        self._patient(pid).collection("memory").document("current").delete()
        self._patient(pid).collection("plans").document("next").delete()

    def delete_account(self, pid):
        sessions = int(self._patient(pid).collection("sessions").count().get()[0][0].value)
        # recursive_delete removes the patient doc and every subcollection under it
        # (sessions + turns, memory, memory_history, flags).
        self._db.recursive_delete(self._patient(pid))
        return sessions

    def get_next_plan(self, pid):
        snap = self._patient(pid).collection("plans").document("next").get()
        return snap.to_dict() if snap.exists else None

    def save_next_plan(self, pid, sid, plan):
        self._patient(pid).collection("plans").document("next").set(
            {**plan, "built_after_session": sid, "built_at": self._fs.SERVER_TIMESTAMP})

    def recent_session_plans(self, pid, n=5):
        query = (self._patient(pid).collection("sessions")
                 .order_by("started_at", direction=self._fs.Query.DESCENDING).limit(n * 3))
        plans = [s.to_dict().get("class_plan") for s in query.stream()]
        return [p for p in plans if p][:n]

    def add_games_recommendation(self, pid, sid, rec):
        ref = self._patient(pid).collection("games_app_recommendations").document(recommendation_id(rec))
        snap = ref.get()
        if snap.exists:
            ref.update({"times_suggested": self._fs.Increment(1), "last_session": sid,
                        "last_seen": self._fs.SERVER_TIMESTAMP})
        else:
            ref.set({**rec, "status": "new", "times_suggested": 1, "first_session": sid,
                     "last_session": sid, "last_seen": self._fs.SERVER_TIMESTAMP})

    def pending_plan_sessions(self, pid, limit=2):
        query = self._patient(pid).collection("sessions").where(
            filter=self._fs.FieldFilter("plan_status", "in", [PLAN_PENDING, PLAN_FAILED]))
        found = [{"id": s.id, **s.to_dict()} for s in query.stream()]
        found = [v for v in found if v.get("plan_attempts", 0) < MAX_PLAN_ATTEMPTS]
        found.sort(key=lambda v: v.get("started_at") or _now(), reverse=True)
        return [v["id"] for v in found[:limit]]

    def get_technique_note(self, pid, note_id):
        snap = self._patient(pid).collection("technique_notes").document(note_id).get()
        return snap.to_dict() if snap.exists else None

    def save_technique_note(self, pid, note_id, note):
        self._patient(pid).collection("technique_notes").document(note_id).set(
            {**note, "created_at": self._fs.SERVER_TIMESTAMP})

    def recent_technique_notes(self, pid, n=3):
        query = (self._patient(pid).collection("technique_notes")
                 .order_by("created_at", direction=self._fs.Query.DESCENDING).limit(n))
        return [s.to_dict() for s in query.stream()]

    def list_sessions(self, pid, n=30):
        query = (self._patient(pid).collection("sessions")
                 .order_by("started_at", direction=self._fs.Query.DESCENDING).limit(n))
        return [{"id": s.id, **s.to_dict()} for s in query.stream()]

    def list_flags(self, pid, n=50):
        query = (self._patient(pid).collection("flags")
                 .order_by("created_at", direction=self._fs.Query.DESCENDING).limit(n))
        return [{"id": s.id, **s.to_dict()} for s in query.stream()]

    def list_recommendations(self, pid):
        recs = [{"id": s.id, **s.to_dict()} for s in self._patient(pid).collection("games_app_recommendations").stream()]
        return sorted(recs, key=lambda v: v.get("last_seen") or _now(), reverse=True)

    def list_memory_history(self, pid, n=20):
        query = (self._patient(pid).collection("memory_history")
                 .order_by("updated_at", direction=self._fs.Query.DESCENDING).limit(n))
        return [{**s.to_dict(), "version": s.id} for s in query.stream()]

    def get_memory_version(self, pid, version):
        snap = self._patient(pid).collection("memory_history").document(version).get()
        return snap.to_dict() if snap.exists else None

    def resolve_flag(self, pid, flag_id, by):
        ref = self._patient(pid).collection("flags").document(flag_id)
        if not ref.get().exists:
            return False
        ref.update({"status": "resolved", "resolved_by": by, "resolved_at": self._fs.SERVER_TIMESTAMP})
        return True

    def set_recommendation_status(self, pid, rec_id, status):
        ref = self._patient(pid).collection("games_app_recommendations").document(rec_id)
        if not ref.get().exists:
            return False
        ref.update({"status": status, "status_updated_at": self._fs.SERVER_TIMESTAMP})
        return True

    def get_notes(self, pid):
        snap = self._patient(pid).collection("caregiver").document("notes").get()
        return snap.to_dict() if snap.exists else None

    def save_notes(self, pid, text, by):
        self._patient(pid).collection("caregiver").document("notes").set(
            {"text": text, "updated_by": by, "updated_at": self._fs.SERVER_TIMESTAMP})

    def save_session_prompt(self, pid, sid, text, version):
        self._session(pid, sid).collection("prompt").document("live").set(
            {"text": text, "prompt_version": version, "saved_at": self._fs.SERVER_TIMESTAMP})

    def get_session_prompt(self, pid, sid):
        snap = self._session(pid, sid).collection("prompt").document("live").get()
        return snap.to_dict() if snap.exists else None

    def get_settings(self, pid):
        snap = self._patient(pid).collection("caregiver").document("settings").get()
        return snap.to_dict() if snap.exists else None

    def get_billing_state(self):
        snap = self._db.collection("usage").document("billing").get()
        return snap.to_dict() if snap.exists else None

    def set_billing_state(self, state):
        self._db.collection("usage").document("billing").set(state)

    def add_push_subscription(self, pid, sub_id, sub):
        self._patient(pid).set({"created_at": self._fs.SERVER_TIMESTAMP}, merge=True)
        self._patient(pid).collection("push_subscriptions").document(sub_id).set(
            {**sub, "created_at": self._fs.SERVER_TIMESTAMP})

    def list_push_subscriptions(self, pid):
        return [{"id": s.id, **s.to_dict()} for s in self._patient(pid).collection("push_subscriptions").stream()]

    def remove_push_subscription(self, pid, sub_id):
        self._patient(pid).collection("push_subscriptions").document(sub_id).delete()

    def get_reminder_settings(self, pid):
        snap = self._patient(pid).collection("caregiver").document("reminder").get()
        return snap.to_dict() if snap.exists else None

    def save_reminder_settings(self, pid, settings):
        self._patient(pid).collection("caregiver").document("reminder").set(settings)

    def get_reminder(self, pid, doc_id):
        snap = self._patient(pid).collection("reminders").document(doc_id).get()
        return snap.to_dict() if snap.exists else None

    def save_reminder(self, pid, doc_id, record):
        self._patient(pid).collection("reminders").document(doc_id).set(record)

    def list_reminders(self, pid, n=10):
        query = (self._patient(pid).collection("reminders")
                 .order_by("at", direction=self._fs.Query.DESCENDING).limit(n))
        return [{"id": s.id, **s.to_dict()} for s in query.stream()]

    def save_settings(self, pid, settings, by):
        self._patient(pid).collection("caregiver").document("settings").set(
            {**settings, "updated_by": by, "updated_at": self._fs.SERVER_TIMESTAMP})

    def research_runs_on(self, pid, day):
        snap = self._patient(pid).collection("research_usage").document(day).get()
        return int((snap.to_dict() or {}).get("runs", 0)) if snap.exists else 0

    def add_research_run(self, pid, day):
        self._patient(pid).collection("research_usage").document(day).set(
            {"runs": self._fs.Increment(1)}, merge=True)

    def searches_in_month(self, month, provider="tavily"):
        snap = self._db.collection("usage").document(f"{provider}-{month}").get()
        return int((snap.to_dict() or {}).get("searches", 0)) if snap.exists else 0

    def add_search(self, month, provider="tavily"):
        self._db.collection("usage").document(f"{provider}-{month}").set(
            {"searches": self._fs.Increment(1)}, merge=True)

    def add_flag(self, pid, sid, flag):
        self._patient(pid).collection("flags").document().set({
            **flag, "session_id": sid, "created_at": self._fs.SERVER_TIMESTAMP, "status": "open",
        })
