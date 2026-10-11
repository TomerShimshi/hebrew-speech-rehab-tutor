"""Deterministic spaced-retrieval bookkeeping for practiced words (no LLM).

The model only reports *what happened* (uncued / cued / failed, or -- for a name in free talk
that wasn't practiced -- self_found / not_found); the schedule is plain code:
  uncued, self_found -> interval doubles (1, 2, 4, 8 ... capped at 30 days)
  cued               -> practice again tomorrow
  failed, not_found  -> practice again next session (due today)
A name that was only ever asked in the names game (source "probe", an untreated item) is never
scheduled for practice: practicing it would spoil the comparison (12).
"""

import datetime as dt

from app.schemas import WordResult, WordSource, WordStats

MAX_INTERVAL_DAYS = 30


def merged_source(old: WordSource | None, new: WordSource) -> WordSource:
    """Practiced wins (it can't be undone); otherwise a name keeps where it first came from."""
    if new is WordSource.practiced or old is None:
        return new
    return old


def record(stats: WordStats | None, result: WordResult, today: dt.date, *,
           cue_level: str | None = None, low_confidence: bool = False,
           source: WordSource = WordSource.practiced) -> WordStats:
    s = stats.model_copy() if stats else WordStats(source=source)
    s.source = merged_source(stats.source if stats else None, source)
    s.attempts += 1
    setattr(s, result.value, getattr(s, result.value) + 1)
    if low_confidence:
        s.low_confidence += 1
    s.last_result = result
    s.last_cue_level = cue_level
    s.last_seen = today.isoformat()
    if s.source is WordSource.probe:
        s.interval_days, s.next_due = 0, None  # never practiced while it's an untreated item
        return s
    if result is WordResult.self_found and low_confidence:
        return s  # maybe a misheard name: shown, but it doesn't move the schedule
    if result in (WordResult.uncued, WordResult.self_found):
        s.interval_days = min(MAX_INTERVAL_DAYS, max(1, s.interval_days * 2))
    elif result is WordResult.cued:
        s.interval_days = 1
    else:
        s.interval_days = 0
    s.next_due = (today + dt.timedelta(days=s.interval_days)).isoformat()
    return s


def is_treated(stats: WordStats | None) -> bool:
    return stats is not None and stats.source is WordSource.practiced


def due_words(bank: dict[str, WordStats], today: dt.date, limit: int = 10) -> list[str]:
    """Words due for practice, most overdue first (used by the lesson plan in 05). Names he
    couldn't find in free talk come first: they're the best next practice items (12)."""
    due = [(w, s) for w, s in bank.items() if s.next_due and s.next_due <= today.isoformat()]
    due.sort(key=lambda ws: (ws[1].source is not WordSource.not_found, ws[1].next_due, -ws[1].failed))
    return [w for w, _ in due[:limit]]
