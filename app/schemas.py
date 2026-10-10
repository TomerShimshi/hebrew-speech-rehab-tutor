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


class ProbeItem(BaseModel):
    target: str = Field(description="HEBREW: the name/word he should come up with.")
    kind: str = Field(description="'treated' (practiced before, from the word bank) or 'untreated' (new, same kind)")
    elicit: str = Field(description="HEBREW: exactly how she asks for it, WITHOUT hints (a description).")
    bridge: str = Field(default="", description="HEBREW: the natural lead-in she says, linking it to a topic he talks about.")
    about_his_life: bool = Field(default=False, description=(
        "true if the answer comes from HIS OWN life (his family, friends, his places, his events) -- "
        "then it MUST be a name found in the memory/profile/notes/word bank or said by him; never invented."))


class PracticeItem(BaseModel):
    target: str = Field(description="HEBREW: the name/word to practice.")
    elicit: str = Field(description="HEBREW: exactly how she asks for it.")
    hint_meaning: str = Field(description="HEBREW: hint 1, its meaning/context, as she says it.")
    # as spoken, e.g. "טְבֶ..." -- never the letter's name
    hint_first_syllable: str = Field(description="HEBREW: hint 2, the first syllable as spoken, with vowel marks (e.g. 'טְבֶ...').")
    sentence_completion: str = Field(description="HEBREW: hint 3, a sentence for him to complete.")
    about_his_life: bool = Field(default=False, description=(
        "true if the answer comes from HIS OWN life (his family, friends, his places, his events) -- "
        "then it MUST be a name found in the memory/profile/notes/word bank or said by him; never invented."))


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
    recall_from_last_time: str = Field(default="", description="HEBREW: one sentence she says in her greeting, recalling last time.")
    warmup: str = Field(default="", description="HEBREW: the easy opener she says.")
    # 3-5 uncued check-in items every regular session: the progress measurement (05).
    probe: list[ProbeItem] = Field(default=[], min_length=0, json_schema_extra={"minItems": 3, "maxItems": 5})
    practice: list[PracticeItem] = []
    activity: str = Field(default="", description="ENGLISH: the main activity, as instructions to her (a quoted Hebrew word is fine).")
    conversation_topics: list[str] = Field(default=[], description="ENGLISH: up to 3 topics.")
    homework: str = Field(default="", description="ENGLISH: the small task for next time (she says it in Hebrew).")
    fatigue_fallback: str = Field(default="", description="ENGLISH: an easy activity he will surely succeed at.")
    avoid: list[str] = Field(default=[], description="ENGLISH: topics or approaches to avoid.")
    # games (sub-plan 06)
    game_homework: list[GameHomework] = []
    games_note: str = Field(default="", description="ENGLISH: one fact about his recent games she may mention naturally.")
    # an in-session activity built on what he actually played (its category / words) -- turns
    # the game into talking practice, e.g. "tell me about a time you fixed something: which tools?"
    games_link_activity: str = Field(default="", description="ENGLISH: a short talking activity built on what he played.")
    games_app_feedback: list[GamesAppFeedback] = []
    # For the caregiver page only (never rendered for the tutor).
    notes_applied: str = Field(default="", description=(
        "ENGLISH, one sentence: how this plan applies the NOTES FROM THE FAMILY / THERAPIST; "
        "empty if there are no notes."))

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
            "notes_applied": cut(self.notes_applied, 300),
        })
