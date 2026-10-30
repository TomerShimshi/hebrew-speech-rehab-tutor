"""Leaving a conversation out (20.5): it stays visible and marked, but nothing that learns reads it.

The readers skip it through `list_sessions` (the store's one filter). What its processing already left
in shared docs -- its memory summary, its names-game results, its needs entries -- is removed here,
exactly, and kept on the session (`left_out_traces`) so putting it back restores the same entries.
No model calls: a put-back that needs the memory agent goes through the existing "process now"."""

import datetime as dt

from app import check_in_set
from app.memory_text import render_memory
from app.store import MEM_DONE, MEM_FAILED, MEM_PENDING, MEM_PROCESSING, SessionStore

MEM_EXCLUDED = "excluded"  # memory_status of a left-out session that was never processed


class LeaveOutBusy(Exception):
    """Its memory update is running right now: wait a minute (never half-applied)."""


def _log(message: str) -> None:
    print(f"[leave-out] {message}", flush=True)


def _by_date(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=lambda e: e.get("date") or "")


def _save_memory_with(store: SessionStore, pid: str, memory: dict, recent: list[dict], version: str) -> None:
    new = {**memory, "recent_summaries": recent}
    new.pop("updated_at", None)
    new["memory_prompt"] = render_memory(new)
    store.save_memory(pid, version, new, memory)


def _remove_summary(store: SessionStore, pid: str, sid: str) -> list[dict]:
    memory = store.get_memory(pid)
    mine = [r for r in (memory or {}).get("recent_summaries") or [] if r.get("session_id") == sid]
    if mine:
        _save_memory_with(store, pid, memory, [r for r in memory["recent_summaries"] if r not in mine],
                          f"leave-out-{sid}")
    return mine


def _remove_needs(store: SessionStore, pid: str, sid: str) -> tuple[list[dict], list[dict]]:
    needs = store.get_needs(pid)
    if not needs:
        return [], []
    history, areas = [], {}
    for area, a in (needs.get("areas") or {}).items():
        mine = [h for h in a.get("history") or [] if h.get("session") == sid]
        history += [{"area": area, "entry": h} for h in mine]
        areas[area] = {**a, "history": [h for h in a["history"] if h not in mine]} if mine else a
    have = needs.get("therapist_points") or []
    points = [{"index": i, "point": p} for i, p in enumerate(have) if p.get("session") == sid]  # put back in place
    if history or points:
        store.save_needs(pid, {**needs, "areas": areas,
                               "therapist_points": [p for p in have if p.get("session") != sid]})
    return history, points


def leave_out(store: SessionStore, pid: str, sid: str, by: str) -> dict:
    """{"was_processed", "is_latest", "rebuild"}. Marks the session first, then the cleanups; each is
    idempotent, so pressing again finishes a cleanup that failed half way. KeyError: no such session."""
    session = store.get_session(pid, sid)
    if session is None:
        raise KeyError(sid)
    status = session.get("memory_status")
    if status == MEM_PROCESSING:
        raise LeaveOutBusy(sid)
    fields = {"excluded": True, "excluded_by": by,
              "excluded_at": session.get("excluded_at") or dt.datetime.now(dt.timezone.utc)}
    if status in (MEM_PENDING, MEM_FAILED):  # never processed: the sweep must not take it
        fields.update(memory_status=MEM_EXCLUDED, memory_status_before=status)
    store.update_session(pid, sid, fields)

    found = {"summaries": _remove_summary(store, pid, sid)}
    current_set = store.get_check_in_set(pid)
    found["check_in"] = check_in_set.remove_session(current_set, sid) if current_set else []
    if found["check_in"]:
        store.save_check_in_set(pid, current_set)
    found["needs_history"], found["needs_points"] = _remove_needs(store, pid, sid)
    traces = dict(session.get("left_out_traces") or {})
    for key, items in found.items():  # pressed again: what is already kept stays kept
        traces[key] = [*traces.get(key, []), *items]
    store.update_session(pid, sid, {"left_out_traces": traces})

    out = {"was_processed": status == MEM_DONE,
           "is_latest": status == MEM_DONE and (store.get_memory(pid) or {}).get("last_session_id") == sid,
           "rebuild": (store.get_next_plan(pid) or {}).get("built_after_session") == sid}
    _log(f"{pid}/{sid} left out by {by}: {out}")
    return out


def _restore_summaries(store: SessionStore, pid: str, sid: str, summaries: list[dict]) -> None:
    memory = store.get_memory(pid)
    recent = list((memory or {}).get("recent_summaries") or [])
    back = [r for r in summaries if r not in recent]
    if memory and back:
        _save_memory_with(store, pid, memory, _by_date(recent + back), f"put-back-{sid}")


def _restore_needs(store: SessionStore, pid: str, history: list[dict], points: list[dict]) -> None:
    needs = store.get_needs(pid)
    if not needs or not (history or points):
        return
    areas = {k: dict(v) for k, v in (needs.get("areas") or {}).items()}
    for h in history:
        a = areas.get(h["area"])
        if a is not None and h["entry"] not in (a.get("history") or []):
            a["history"] = _by_date([*a.get("history", []), h["entry"]])
    pts = list(needs.get("therapist_points") or [])
    for p in points:  # in their old places, in order
        if p["point"] not in pts:
            pts.insert(min(p["index"], len(pts)), p["point"])
    store.save_needs(pid, {**needs, "areas": areas, "therapist_points": pts})


def put_back(store: SessionStore, pid: str, sid: str, *, restored_away: bool) -> dict:
    """{"process": bool}: True when the page should call the existing /process -- it was never processed,
    or its memory was restored away (then its processing runs again and writes its traces itself)."""
    session = store.get_session(pid, sid)
    if session is None:
        raise KeyError(sid)
    if not session.get("excluded"):
        return {"process": False}  # already back: nothing twice
    # never processed (incl. left out while still active, then ended: pending), or restored away
    if (session.get("memory_status") in (MEM_EXCLUDED, MEM_PENDING, MEM_FAILED, None) or restored_away
            or session.get("memory_restored_away")):
        store.update_session(pid, sid, {"excluded": False, "memory_status": MEM_PENDING, "memory_error": None,
                                        "left_out_traces": None, "memory_restored_away": False})
        _log(f"{pid}/{sid} put back: to be processed again")
        return {"process": True}
    traces = session.get("left_out_traces") or {}
    _restore_summaries(store, pid, sid, traces.get("summaries") or [])
    current_set = store.get_check_in_set(pid)
    if current_set and check_in_set.restore_session(current_set, traces.get("check_in") or []):
        store.save_check_in_set(pid, current_set)
    _restore_needs(store, pid, traces.get("needs_history") or [], traces.get("needs_points") or [])
    store.update_session(pid, sid, {"excluded": False, "left_out_traces": None})
    _log(f"{pid}/{sid} put back: its traces restored")
    return {"process": False}
