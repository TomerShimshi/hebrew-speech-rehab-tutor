"""Pydantic models for the agent calls: memory, word bank, summaries, flags."""

from enum import Enum

from pydantic import BaseModel, Field

from app.steps import NamesGameStep, PlanStep, ProbeItem  # noqa: F401 -- ProbeItem re-exported

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
    # A name in free talk that the tutor didn't practice or ask (12), with visible effort:
    self_found = "self_found"  # he found it himself
    not_found = "not_found"  # he tried and gave up, or talked around it


class WordSource(str, Enum):
    """Where a word-bank name came from (12). Only `practiced` makes a name "treated" in the
    names game; the others were never trained, so they'd spoil the treated/untreated comparison."""
    practiced = "practiced"  # the tutor practiced it with him (hints / practice items)
    self_found = "self_found"  # found on his own in free talk
    not_found = "not_found"  # missed in free talk
    probe = "probe"  # only asked in the names game (an untreated item)


class WordStats(BaseModel):
    attempts: int = 0
    uncued: int = 0
    cued: int = 0
    failed: int = 0
    self_found: int = 0
    not_found: int = 0
    # Old entries have no source: they were practiced or check-in items before 12, so practiced.
    source: WordSource = WordSource.practiced
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
    tutor_issue = "tutor_issue"  # the tutor made a mistake (8.5): for the caregivers to review


class Severity(str, Enum):
    low = "low"
    high = "high"


class Flag(BaseModel):
    kind: FlagKind
    severity: Severity
    evidence: str = Field(max_length=1000)
    # tutor_issue (8.5): the exchange as separate fields, so the page never mixes the English
    # explanation and the Hebrew quotes in one line
    issue: str = ""  # invented_fact | insisted | wrong_language | cut_off | other
    tutor_said: str = Field(default="", max_length=600)
    he_said: str = Field(default="", max_length=600)


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


# ---- per-account session settings (sub-plan 09), set on the caregiver page ----------------------

class VoiceSettings(BaseModel):
    # Silence before she answers (automatic mode); 0 = none set: Gemini decides when he's done.
    silence_ms: int = Field(default=3000, ge=0, le=8000)
    silence_auto: bool = True  # adjusted after each session (app/voice_tuning.py) unless the family fixed it
    noise_level: int = Field(default=0, ge=0, le=3)  # browser noise filter while she speaks (0 = off)
    noise_auto: bool = True
    tap_to_talk: bool = False  # he taps to start / end his turn instead of automatic detection
    record_audio: bool = True  # record the session (both voices) for the caregiver page (09)


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


# Field languages (08): English for every instruction/description (readable for the family,
# followed reliably by the models); Hebrew ONLY for the exact words the tutor says and the
# target names (correct Hebrew and genders, instead of the live model translating on the fly).

class PrimaryGoal(BaseModel):
    type: GoalType
    description: str = Field(description="ENGLISH: what this session works on, and why.")


class CheckInItem(BaseModel):
    """One name in the names game (12): asked the same way every time."""
    target: str = Field(description="HEBREW: the name he should come up with.")
    question: str = Field(description="HEBREW: the fixed describing question she asks, WITHOUT hints, in her voice.")
    about_his_life: bool = Field(default=False, description=(
        "true if the answer comes from HIS OWN life (his people, his places, his events) -- then it MUST be a "
        "name found in the memory/profile/notes or said by him; never invented."))
    kind: str = Field(default="untreated", description="Set by code: 'treated' only if practiced in the word bank.")


class CheckInProposal(BaseModel):
    """The plan builder's proposal for a new names-game set (12)."""
    items: list[CheckInItem] = Field(json_schema_extra={"minItems": 6, "maxItems": 10})
    rationale: str = Field(default="", description="ENGLISH, one sentence: how the set was chosen (for the family).")


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
    """The lesson plan (05): session-level parts + an ORDERED list of steps (13.5). Built by the
    plan builder with tools (app/agent/plan_tools.py); the intro plan is fixed (prompts/intro_plan.yaml)."""
    plan_type: str = "regular"  # 'intro' or 'regular'
    primary_goal: PrimaryGoal
    steps: list[PlanStep] = []
    homework: str = ""  # ENGLISH: the small task for next time (she says it, in the closing only)
    fatigue_fallback: str = ""  # ENGLISH: an easy activity he will surely succeed at
    avoid: list[str] = []  # ENGLISH: topics or approaches to avoid
    game_homework: list[GameHomework] = []  # games (06)
    games_note: str = ""  # ENGLISH: one fact about his recent games she may mention naturally
    # For the caregiver page only (never rendered for the tutor).
    notes_applied: str = ""
    estimated_minutes: float = 0  # the builder's time estimate at his pace (13.5)

    @property
    def names_game(self) -> "NamesGameStep | None":
        return next((s for s in self.steps if s.kind == "names_game"), None)

    @property
    def probe(self) -> list[ProbeItem]:
        """The names game's items (filled at session start), as scored by the memory update."""
        game = self.names_game
        return list(game.items) if game else []
