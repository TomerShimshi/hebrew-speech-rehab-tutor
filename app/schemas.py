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


# ---- research findings (sub-plan 07) -------------------------------------------------------

class Confidence(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Technique(BaseModel):
    name: str = Field(description="Short name of the technique, e.g. 'Semantic Feature Analysis'.")
    how_to: str = Field(description="How the voice tutor can do it in a short home session, 2-4 sentences.")
    hebrew_example: str = Field(description="One short example of how it sounds in Hebrew.")
    source_url: str = Field(description="The URL (exactly as a search returned it) that supports it.")


class ResearchFindings(BaseModel):
    summary: str = Field(description="2-4 sentences: what the sources say about the question.")
    techniques: list[Technique] = Field(description="0-3 techniques; empty if nothing reliable was found.")
    confidence: Confidence


# ---- lesson plan (sub-plan 05) -------------------------------------------------------------
# No length caps in the schema sent to Gemini (it handles plain schemas most reliably);
# ClassPlan.tidy() trims anything oversized after parsing.

class GoalType(str, Enum):
    intro = "intro"  # first session / after "forget memory": getting to know him
    name_retrieval = "name_retrieval"  # people & places, esp. from his own life
    discourse = "discourse"  # telling a story in order, explaining step by step
    high_level_language = "high_level_language"  # category naming, synonyms, sayings
    conversation = "conversation"  # an easier free-talk day


class PrimaryGoal(BaseModel):
    type: GoalType
    description: str


class ProbeItem(BaseModel):
    target: str  # the word/name he should come up with
    kind: str = Field(description="'treated' (practiced before, from the word bank) or 'untreated' (new, same kind)")
    elicit: str  # how the tutor asks for it WITHOUT hints (e.g. a description)
    bridge: str = Field(default="", description="A natural lead-in linking it to a topic he is likely to talk about")


class PracticeItem(BaseModel):
    target: str
    elicit: str
    hint_meaning: str
    hint_first_syllable: str  # as spoken, e.g. "טְבֶ..." -- never the letter's name
    sentence_completion: str


class GameHomework(BaseModel):
    game_id: str = Field(description="A game id from the GAMES section")
    why: str = Field(description="One short line linking it to today's goal, in English")
    name_he: str = ""  # filled in by code from the catalog


class GamesAppFeedback(BaseModel):
    game_id: str
    kind: str = Field(description="tune_difficulty | bug | ux | new_game | platform")
    title: str
    rationale: str
    evidence: str


class ClassPlan(BaseModel):
    plan_type: str = Field(description="'intro' or 'regular'")
    primary_goal: PrimaryGoal
    recall_from_last_time: str = ""
    warmup: str = ""
    # 3-5 uncued check-in items every regular session: the progress measurement (05).
    probe: list[ProbeItem] = Field(default=[], min_length=0, json_schema_extra={"minItems": 3, "maxItems": 5})
    practice: list[PracticeItem] = []
    activity: str = ""
    conversation_topics: list[str] = []
    homework: str = ""
    fatigue_fallback: str = ""
    avoid: list[str] = []
    # games (sub-plan 06)
    game_homework: list[GameHomework] = []
    games_note: str = ""  # one natural line the tutor may use about his recent games
    # an in-session activity built on what he actually played (its category / words) -- turns
    # the game into talking practice, e.g. "tell me about a time you fixed something: which tools?"
    games_link_activity: str = ""
    games_app_feedback: list[GamesAppFeedback] = []

    def tidy(self) -> "ClassPlan":
        """Trim to sane sizes (the model occasionally over-delivers)."""
        def cut(text: str, n: int = 400) -> str:
            return " ".join((text or "").split())[:n]

        return self.model_copy(update={
            "plan_type": "intro" if self.plan_type == "intro" else "regular",
            "primary_goal": self.primary_goal.model_copy(update={"description": cut(self.primary_goal.description, 600)}),
            "recall_from_last_time": cut(self.recall_from_last_time),
            "warmup": cut(self.warmup),
            "probe": [p.model_copy(update={"kind": "treated" if p.kind == "treated" else "untreated"})
                      for p in self.probe[:5]],
            "practice": self.practice[:8],
            "activity": cut(self.activity, 600),
            "conversation_topics": [cut(t, 150) for t in self.conversation_topics[:3]],
            "homework": cut(self.homework),
            "fatigue_fallback": cut(self.fatigue_fallback),
            "avoid": [cut(a, 150) for a in self.avoid[:8]],
            "game_homework": self.game_homework[:2],
            "games_note": cut(self.games_note, 300),
            "games_link_activity": cut(self.games_link_activity, 500),
            "games_app_feedback": self.games_app_feedback[:2],
        })
