"""Deterministic spaced-retrieval bookkeeping for practiced words (no LLM).

The model only reports *what happened* (uncued / cued / failed); the schedule is plain code:
  uncued -> interval doubles (1, 2, 4, 8 ... capped at 30 days)
  cued   -> practice again tomorrow
  failed -> practice again next session (due today)
"""

import datetime as dt

from app.schemas import WordResult, WordStats

MAX_INTERVAL_DAYS = 30


def record(stats: WordStats | None, result: WordResult, today: dt.date, *,
           cue_level: str | None = None, low_confidence: bool = False) -> WordStats:
    s = stats.model_copy() if stats else WordStats()
    s.attempts += 1
    setattr(s, result.value, getattr(s, result.value) + 1)
    if low_confidence:
        s.low_confidence += 1
    s.last_result = result
    s.last_cue_level = cue_level
    s.last_seen = today.isoformat()
    if result is WordResult.uncued:
        s.interval_days = min(MAX_INTERVAL_DAYS, max(1, s.interval_days * 2))
    elif result is WordResult.cued:
        s.interval_days = 1
    else:
        s.interval_days = 0
    s.next_due = (today + dt.timedelta(days=s.interval_days)).isoformat()
    return s


def due_words(bank: dict[str, WordStats], today: dt.date, limit: int = 10) -> list[str]:
    """Words due for practice, most overdue first (used by the lesson plan in 05)."""
    due = [(w, s) for w, s in bank.items() if s.next_due and s.next_due <= today.isoformat()]
    due.sort(key=lambda ws: (ws[1].next_due, -ws[1].failed))
    return [w for w, _ in due[:limit]]
