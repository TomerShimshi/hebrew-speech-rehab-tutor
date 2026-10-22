"""Measuring like a therapist (sub-plan 17): plain code, no LLM.

- The connected-speech probe: a fixed short story she tells and he retells, asked the same way every
  time, scored by the main ideas he conveyed. Stories come from prompts/probe_stories.yaml in a fixed
  rotation; each is told twice (its first telling is its baseline), so the scores compare like with like.
- His own view: every ~2 weeks one short question at the end of a session ("how was talking with
  people this week?"), recorded 1-5 with his words.
- Conversation measures: from the transcript, by code (how long his answers are).
Both probe steps are placed by code (never by the plan builder), outside its time budget.
"""

import datetime as dt
from functools import lru_cache

import yaml

from app.config import REPO_ROOT

STORIES_PATH = REPO_ROOT / "prompts" / "probe_stories.yaml"
PROBE_EVERY = 2  # a story probe every other regular session
TELLINGS = 2  # each story is told this many times before the next one
VIEW_EVERY_DAYS = 14


@lru_cache
def stories() -> list[dict]:
    return yaml.safe_load(STORIES_PATH.read_text(encoding="utf-8"))["stories"]


def _regular_ended(sessions: list[dict]) -> list[dict]:
    """Ended regular sessions, newest first (as the store lists them)."""
    return [s for s in sessions if s.get("status") == "ended"
            and (s.get("class_plan") or {}).get("plan_type") == "regular"]


def story_due(sessions: list[dict]) -> dict | None:
    """The story for the next plan, or None when it's not a probe session. `sessions`: newest first."""
    regular = _regular_ended(sessions)
    since = next((i for i, s in enumerate(regular) if s.get("story_probe")), len(regular))
    if since + 1 < PROBE_EVERY:  # the last probe was in the previous session
        return None
    done = sum(1 for s in regular if (s.get("story_probe") or {}).get("status") in ("done", "skipped"))
    all_ = stories()
    return all_[(done // TELLINGS) % len(all_)]


def story_result(step, reported: dict | None) -> dict | None:
    """The session's probe result, scored by code from the main ideas the agent heard."""
    if step is None:
        return None
    base = {"story_id": step.story_id, "title": step.title, "ideas": len(step.main_ideas)}
    if not reported:
        return {**base, "status": "not_reported"}
    if reported.get("skipped"):
        return {**base, "status": "skipped"}
    got = {c for c in reported.get("conveyed") or [] if isinstance(c, int) and 1 <= c <= len(step.main_ideas)}
    return {**base, "status": "done", "ideas_conveyed": len(got), "conveyed": sorted(got),
            "ideas_pct": round(100 * len(got) / len(step.main_ideas)),
            "low_confidence": bool(reported.get("low_confidence"))}


def view_due(sessions: list[dict], today: dt.date) -> bool:
    """His own view is due: none recorded in the last ~2 weeks (regular sessions)."""
    for s in _regular_ended(sessions):
        if (s.get("his_view") or {}).get("status") == "done":
            started = s.get("started_at")
            day = started.date() if hasattr(started, "date") else today
            return (today - day).days >= VIEW_EVERY_DAYS
    return bool(_regular_ended(sessions))  # never asked yet: after his first regular session


def talk_measures(turns: list[dict]) -> dict:
    """How he talked, by code: the number of his answers and their average length in words."""
    answers = [len((t.get("text") or t.get("live_text") or "").split()) for t in turns if t.get("speaker") == "patient"]
    answers = [n for n in answers if n]
    return {"answers": len(answers), "avg_words": round(sum(answers) / len(answers), 1) if answers else 0,
            "long_answers": sum(1 for n in answers if n >= 12)}
