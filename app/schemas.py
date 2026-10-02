"""Pydantic models for the agent calls: memory, word bank, summaries, flags."""

from enum import Enum

from pydantic import BaseModel, Field

SECTION_NAMES = (
    "personal_facts",  # people, places and life events he shared
    "interests",  # topics he enjoys talking about
    "what_works",  # hints and approaches that helped him
    "what_to_avoid",  # frustrations, sensitive topics
    "language_observations",  # retrieval patterns, e.g. "names of places: needs the first syllable"
    "homework_given",  # the small task(s) the tutor gave for next time
)
MAX_ITEMS_PER_SECTION = 25
MAX_ITEM_CHARS = 200


class MemorySections(BaseModel):
    personal_facts: list[str] = []
    interests: list[str] = []
    what_works: list[str] = []
    what_to_avoid: list[str] = []
    language_observations: list[str] = []
    homework_given: list[str] = []


class WordResult(str, Enum):
    uncued = "uncued"  # retrieved on his own
    cued = "cued"  # retrieved after a hint
    failed = "failed"  # the tutor had to give the word


class WordStats(BaseModel):
    attempts: int = 0
    uncued: int = 0
    cued: int = 0
    failed: int = 0
    low_confidence: int = 0  # attempts where the transcript was uncertain
    last_result: WordResult | None = None
    last_cue_level: str | None = None
    last_seen: str | None = None  # ISO date
    interval_days: int = 0
    next_due: str | None = None  # ISO date: when to practice it again


class Mood(str, Enum):
    good = "good"
    ok = "ok"
    low = "low"
    unknown = "unknown"


class SessionSummary(BaseModel):
    summary: str = Field(max_length=1500)
    topics: list[str] = Field(default=[], max_length=10)
    mood: Mood = Mood.unknown
    highlights: list[str] = Field(default=[], max_length=10)
    difficulties: list[str] = Field(default=[], max_length=10)


class FlagKind(str, Enum):
    sudden_decline = "sudden_decline"
    distress = "distress"
    safety = "safety"
    technical = "technical"


class Severity(str, Enum):
    low = "low"
    high = "high"


class Flag(BaseModel):
    kind: FlagKind
    severity: Severity
    evidence: str = Field(max_length=1000)


class ConsolidatedMemory(BaseModel):
    """Structured output of the consolidation phase."""

    memory_prompt: str = Field(description="Compact memory for the tutor, max ~500 words.")
    focus_next_session: list[str] = Field(description="2-4 concrete focus points for next time.")


class MemoryDoc(BaseModel):
    """patients/{pid}/memory/current"""

    memory_prompt: str = ""
    sections: MemorySections = MemorySections()
    word_bank: dict[str, WordStats] = {}
    focus_next_session: list[str] = []
    last_session_id: str | None = None
    sessions_processed: int = 0
    prompt_version: str | None = None
