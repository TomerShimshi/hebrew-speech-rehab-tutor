"""Automatic voice settings per account (sub-plan 09), adjusted after every session -- in code.

Two problems pull in opposite directions, so there are two knobs, each with its own measure:

  she cuts him off   -> her turn is interrupted and his next line starts within 2.5 s of hers
                        (he was still mid-thought), plus "cut_off" tutor-issue reports
                        => silence before she answers: +0.5 s (max 6 s)
  noise interrupts   -> her turn is interrupted and he then says nothing, or one word
                        => noise filter (in the browser, only while she speaks): +1 (max 3)

Two or more in a session raise a knob one step; three clean sessions in a row lower it one
step. A knob the family set to a fixed value is never touched. Every decision is recorded on
the session (permanent, shown on the caregiver page) and logged as one JSON line
(jsonPayload.event="voice_adjust" in Cloud Logging).
"""

import json
import sys

from app.config import Settings
from app.schemas import VoiceSettings
from app.store import SessionStore

CUTOFF_WINDOW_S = 2.5
TRIGGER = 2  # events in one session that raise a knob
CLEAN_STREAK = 3  # sessions in a row without events that lower it
SILENCE_MIN_MS, SILENCE_MAX_MS, SILENCE_STEP_MS = 2500, 6000, 500
NOISE_MAX = 3
MIN_TURNS = 4  # shorter sessions say nothing about his speech


def _words(turn: dict) -> int:
    return len(((turn.get("text") or "") or (turn.get("live_text") or "")).split())


def measure(turns: list[dict], cutoff_reports: int = 0) -> dict:
    """Counts the two kinds of interruption in one session's transcript (ordered by seq)."""
    cut_offs, noise = 0, 0
    for her, nxt in zip(turns, turns[1:]):
        if her.get("speaker") != "tutor" or not her.get("interrupted"):
            continue
        his = nxt if nxt.get("speaker") == "patient" else None
        if his is None or _words(his) <= 1:
            noise += 1  # something stopped her, but he didn't say anything
        elif his.get("t_start_s", 0) - her.get("t_start_s", 0) < CUTOFF_WINDOW_S:
            cut_offs += 1  # she started while he was still talking
        # else: he chose to interrupt her -- fine, not counted
    return {"cut_offs": cut_offs + cutoff_reports, "noise_interruptions": noise}


def decide(current: VoiceSettings, state: dict, measured: dict) -> tuple[VoiceSettings, dict, list[str]]:
    """The rules. Returns the new settings, the new streak state and readable changes."""
    new, state, changes = current.model_copy(), dict(state or {}), []

    if current.silence_auto:
        if measured["cut_offs"] >= TRIGGER:
            state["silence_clean"] = 0
            if current.silence_ms < SILENCE_MAX_MS:
                # from below the automatic range (e.g. a fixed 0 switched to automatic): its minimum
                new.silence_ms = min(SILENCE_MAX_MS, max(SILENCE_MIN_MS, current.silence_ms + SILENCE_STEP_MS))
                changes.append(f"silence {current.silence_ms / 1000:g}s -> {new.silence_ms / 1000:g}s "
                               f"({measured['cut_offs']} cut-offs)")
        else:
            state["silence_clean"] = state.get("silence_clean", 0) + (measured["cut_offs"] == 0)
            if state["silence_clean"] >= CLEAN_STREAK and current.silence_ms > SILENCE_MIN_MS:
                new.silence_ms = max(SILENCE_MIN_MS, current.silence_ms - SILENCE_STEP_MS)
                state["silence_clean"] = 0
                changes.append(f"silence {current.silence_ms / 1000:g}s -> {new.silence_ms / 1000:g}s "
                               f"({CLEAN_STREAK} sessions without cut-offs)")

    if current.noise_auto:
        if measured["noise_interruptions"] >= TRIGGER:
            state["noise_clean"] = 0
            if current.noise_level < NOISE_MAX:
                new.noise_level = current.noise_level + 1
                changes.append(f"noise filter {current.noise_level} -> {new.noise_level} "
                               f"({measured['noise_interruptions']} noise interruptions)")
        else:
            state["noise_clean"] = state.get("noise_clean", 0) + (measured["noise_interruptions"] == 0)
            if state["noise_clean"] >= CLEAN_STREAK and current.noise_level > 0:
                new.noise_level = current.noise_level - 1
                state["noise_clean"] = 0
                changes.append(f"noise filter {current.noise_level} -> {new.noise_level} "
                               f"({CLEAN_STREAK} sessions without noise interruptions)")

    # Still noisy at the strictest filter: suggest tap-to-talk (the family decides).
    state["suggest_tap_to_talk"] = (not current.tap_to_talk and current.noise_level >= NOISE_MAX
                                    and measured["noise_interruptions"] >= TRIGGER)
    return new, state, changes


def current_settings(store: SessionStore, settings: Settings, pid: str) -> tuple[VoiceSettings, dict]:
    saved = store.get_settings(pid) or {}
    fields = {k: saved[k] for k in VoiceSettings.model_fields if k in saved}
    return VoiceSettings(**{"silence_ms": settings.vad_silence_ms, **fields}), dict(saved.get("auto_state") or {})


def adjust_after_session(store: SessionStore, settings: Settings, pid: str, sid: str) -> dict | None:
    """Measures the session, applies the rules, records the decision. Runs once per session
    (from /end and from the hourly sweep); never raises."""
    try:
        session = store.get_session(pid, sid) or {}
        if session.get("voice_decision") is not None:
            return session["voice_decision"]
        turns = store.list_turns(pid, sid)
        current, state = current_settings(store, settings, pid)
        if session.get("voice_used", {}).get("tap_to_talk") or current.tap_to_talk:
            decision = {"skipped": "tap-to-talk (no automatic detection to tune)"}
        elif len(turns) < MIN_TURNS:
            decision = {"skipped": f"too short ({len(turns)} lines)"}
        else:
            reports = sum(1 for f in store.list_flags(pid)
                          if f.get("session_id") == sid and f.get("kind") == "tutor_issue" and f.get("issue") == "cut_off")
            measured = measure(turns, reports)
            new, state, changes = decide(current, state, measured)
            decision = {"measured": measured, "before": current.model_dump(), "after": new.model_dump(),
                        "changes": changes, "suggest_tap_to_talk": state["suggest_tap_to_talk"]}
            last = {"session_id": sid, "changes": changes, "measured": measured,
                    "at": session.get("ended_at") or session.get("started_at")}
            store.save_settings(pid, {**new.model_dump(), "auto_state": {**state, "last": last}}, "auto")
        store.update_session(pid, sid, {"voice_decision": decision})
        print(json.dumps({"severity": "INFO", "event": "voice_adjust", "account": pid, "session_id": sid,
                          "message": f"voice_adjust {pid}: {decision.get('changes') or decision.get('skipped') or 'no change'}",
                          **{k: v for k, v in decision.items() if k != "before"}}, default=str), flush=True)
        return decision
    except Exception as exc:  # noqa: BLE001 -- tuning must never break the end of a session
        print(f"[voice] {pid}/{sid}: FAILED {type(exc).__name__}: {exc!s:.200}", file=sys.stderr, flush=True)
        return None
