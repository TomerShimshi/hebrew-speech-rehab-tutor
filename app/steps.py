"""The plan's steps (sub-plan 13.5): the plan IS an ordered list of these.

Each step type is one class that owns, in one place:
  - its CONTENT fields, written by the plan builder through its tool (`TOOL`);
  - its fixed RULES for the tutor -- the lessons of the live tests (12-13); the model never
    writes them, so they can't drift, and a change reaches every saved plan at once;
  - its GUIDE for the plan builder (how to fill it well) -- the tool's description;
  - MINUTES: about how long it takes at a typical pace (the builder's time budget).
`instruction()` is what the tutor gets as CURRENT STEP: content + rules. Plans are saved as
{kind, ...content}; the rules always come from here.
"""

from typing import Annotated, ClassVar, Literal, Union

from pydantic import BaseModel, Field



class ProbeItem(BaseModel):
    """A names-game question (12): filled by code at session start, from the stable set."""
    target: str = Field(description="HEBREW: the name he should come up with.")
    kind: str = Field(default="untreated", description="'treated' (practiced in the word bank) or 'untreated'.")
    elicit: str = Field(description="HEBREW: exactly how she asks for it, WITHOUT hints.")
    bridge: str = ""  # older plans' check-ins had a lead-in
    about_his_life: bool = False


# Every step ends the same way (12.10: she called next_step right after asking her own follow-up,
# and the next step's question followed at once -- two questions in a row).
FINISHED = ("The step is finished only after he has ANSWERED its last question, including your own follow-up -- "
            "never right after you asked something.")


class Step(BaseModel):
    kind: str
    TOOL: ClassVar[str] = ""  # the plan builder's tool that adds it ("" = added by code)
    GUIDE: ClassVar[str] = ""
    RULES: ClassVar[str] = ""
    MINUTES: ClassVar[float] = 1.0  # default length; measured per account once there is data (13.5)
    # A talking step is a real short conversation, not one question and on (12.10): the shortest it
    # may be counted as (a short measurement means she rushed, not that he's fast), and the fewest
    # of HIS answers before the page lets it end (static/app.js gets them with the steps).
    MIN_MINUTES: ClassVar[float] = 0.0
    MIN_ANSWERS: ClassVar[int] = 1

    def content(self) -> str:
        raise NotImplementedError

    def label(self) -> str:
        """A short name for the caregiver page (a target name, a topic)."""
        return ""

    def names(self) -> list[str]:
        """The names this step asks him for (vocabulary, duplicates)."""
        return []

    def instruction(self) -> str:
        return f"{self.content()} HOW: {self.RULES} {FINISHED}"


class OpeningStep(Step):
    kind: Literal["opening"] = "opening"
    TOOL: ClassVar[str] = "set_opening"
    GUIDE: ClassVar[str] = ("The opening (always the first step). recall: ONE sentence she can use in her greeting, "
                            "recalling something from last time (from the memory). opener: an easy, pleasant question "
                            "at his level. Both in HEBREW, in her voice (a woman; masculine for him).")
    RULES: ClassVar[str] = ("Greet him warmly, ask how he feels and react to what he says (recall ONE thing from last "
                            "time, ask about his games or homework, as the rules say). The step is finished after his "
                            "answer and your reaction.")
    MINUTES: ClassVar[float] = 0.6
    recall: str = Field(default="", description="HEBREW: one sentence recalling last time, for her greeting.")
    opener: str = Field(default="", description="HEBREW: an easy, pleasant opening question.")

    def content(self) -> str:
        parts = ["Opening."]
        if self.recall:
            parts.append(f'Recall from last time: "{self.recall}"')
        if self.opener:
            parts.append(f'Opener: "{self.opener}"')
        return " ".join(parts)


class NamesGameStep(Step):
    kind: Literal["names_game"] = "names_game"
    TOOL: ClassVar[str] = "place_names_game"
    GUIDE: ClassVar[str] = ("Where the short names game goes (the progress measure, 12): usually right after the "
                            "opening. Its names are chosen by code at session start, from the stable set. Once.")
    RULES: ClassVar[str] = ("A short, light game -- never a test. Ask each question word for word, one at a time, "
                            "and give him real time (10 seconds of silence are fine). NO hints. If he finds it, a "
                            "short warm \"נכון!\"; if not, say the name warmly in one sentence and go on -- no second "
                            "try. Don't come back to these names later in the session. The step is finished only "
                            "after his answer to the LAST question. Skip it if he seems tired or low.")
    MINUTES: ClassVar[float] = 1.0
    MIN_ANSWERS: ClassVar[int] = 0  # its own questions are the step
    items: list[ProbeItem] = []  # filled at session start (app/class_plan.py)

    def content(self) -> str:
        questions = " ".join(f'{i}) "{p.elicit}" (answer: {p.target})' for i, p in enumerate(self.items, 1))
        return (f'Names game, {len(self.items)} questions: say "בוא נעשה משחק קצר של שמות: אני אתאר משהו, ואתה '
                f'תגיד לי איך קוראים לזה.", then {questions}.')

    def names(self) -> list[str]:
        return [p.target for p in self.items]


class PracticeStep(Step):
    kind: Literal["practice"] = "practice"
    TOOL: ClassVar[str] = "add_practice"
    GUIDE: ClassVar[str] = (
        "A name to practice, inside a short conversation about a topic from his life or interests (the name comes "
        "up naturally, not as a quiz). Names of people or places -- above all from HIS life (from the memory, "
        "profile, notes or his own words; never invented), or less-famous places of the same kind. Prefer names "
        "he couldn't find on his own, then names due in the word bank, then the names game's TREATED names. Never "
        "an UNTREATED names-game name, never his closest family (wife, children, grandchildren) or his own town. "
        "Hints must really match the name and be correct Hebrew; the first syllable AS SPOKEN, with vowel marks "
        "(e.g. 'טְבֶ...'), never the letter's name.")
    RULES: ClassVar[str] = (
        "A real short conversation about the topic -- a few exchanges, not a quiz: start with an open question "
        "about the topic and follow his answer; at a natural point ask the question. If he's stuck, hints one at a "
        "time in this order: meaning -> first syllable -> sentence to complete -> say it and have him use it in a "
        "sentence. After the name, talk about it with him: follow up on what he says (a memory, a detail, his "
        "opinion).")
    MINUTES: ClassVar[float] = 1.0
    MIN_MINUTES: ClassVar[float] = 0.75
    MIN_ANSWERS: ClassVar[int] = 2
    topic: str = Field(description="ENGLISH: the conversation topic the name fits into, e.g. 'his years at work'.")
    name: str = Field(description="HEBREW: the name he should come up with.")
    question: str = Field(description="HEBREW: how she asks for it, without giving it away.")
    hint_meaning: str = Field(description="HEBREW: hint 1, its meaning or context, as she says it.")
    hint_first_syllable: str = Field(description="HEBREW: hint 2, the first syllable as spoken, with vowel marks.")
    hint_complete: str = Field(description="HEBREW: hint 3, a sentence for him to complete.")
    bridge: str = Field(default="", description="HEBREW: optional lead-in line into the topic, in her voice.")
    about_his_life: bool = Field(default=False, description=(
        "true if the answer comes from HIS OWN life (his people, places, events) -- then it must be in his data."))

    def content(self) -> str:
        bridge = f' Lead-in: "{self.bridge}"' if self.bridge else ""
        return (f"Practice, inside a conversation about {self.topic}.{bridge} Ask: \"{self.question}\" (answer: "
                f"{self.name}). Hints: meaning \"{self.hint_meaning}\" -> first syllable "
                f"\"{self.hint_first_syllable}\" -> complete \"{self.hint_complete}\".")

    def label(self) -> str:
        return self.name

    def names(self) -> list[str]:
        return [self.name]


class ActivityStep(Step):
    kind: Literal["activity"] = "activity"
    TOOL: ClassVar[str] = "add_activity"
    GUIDE: ClassVar[str] = (
        "A main activity, from the TECHNIQUES (discourse: telling a story in order, explaining a procedure step by "
        "step; high-level language: category fluency, synonyms, sayings), tied to his interests, at HIS level, "
        "voice only. Instructions to her in ENGLISH (a quoted Hebrew word is fine).")
    RULES: ClassVar[str] = ("Give it time and let him complete it; help gently if he's stuck. The step is finished "
                            "when he has completed it.")
    MINUTES: ClassVar[float] = 2.0
    MIN_MINUTES: ClassVar[float] = 1.5
    MIN_ANSWERS: ClassVar[int] = 2
    instructions: str = Field(description="ENGLISH: the activity, as instructions to her.")
    why: str = Field(default="", description="ENGLISH: one short sentence -- what it practices.")

    def content(self) -> str:
        return f"Activity: {self.instructions}"


class GamesActivityStep(Step):
    kind: Literal["games_activity"] = "games_activity"
    TOOL: ClassVar[str] = "add_games_activity"
    GUIDE: ClassVar[str] = ("Only when he played recently (GAMES): a short TALKING activity built on the category or "
                            "the actual words he played, e.g. after tools: 'tell me about a time you fixed something "
                            "at home'. ENGLISH instructions.")
    RULES: ClassVar[str] = ("Turn the game into talking practice -- never a quiz on its words. Follow what he says. "
                            "The step is finished after a short exchange about it.")
    MINUTES: ClassVar[float] = 1.2
    MIN_MINUTES: ClassVar[float] = 1.0
    MIN_ANSWERS: ClassVar[int] = 2
    instructions: str = Field(description="ENGLISH: the talking activity, built on what he played.")

    def content(self) -> str:
        return f"Game-linked activity: {self.instructions}"


class ThreadStep(Step):
    kind: Literal["thread"] = "thread"
    TOOL: ClassVar[str] = "add_thread"
    GUIDE: ClassVar[str] = ("A conversation thread from his life or interests (the memory), with one concrete opening "
                            "question in HEBREW and 1-2 follow-up ideas. Good for filling the time budget with real "
                            "talk, and for a fast talker.")
    RULES: ClassVar[str] = ("A real short conversation about the topic -- a few exchanges, not one question: ask, "
                            "listen, and follow up at least twice on his OWN words (a detail he mentioned, how he "
                            "felt, his opinion, what happened next). Share a short reaction of your own like a "
                            "person would. Let him tell it fully.")
    MINUTES: ClassVar[float] = 1.0
    MIN_MINUTES: ClassVar[float] = 1.0
    MIN_ANSWERS: ClassVar[int] = 3
    topic: str = Field(description="ENGLISH: the topic, e.g. 'his ping-pong plans'.")
    question: str = Field(description="HEBREW: a concrete opening question, in her voice.")
    follow_ups: str = Field(default="", description="ENGLISH: 1-2 follow-up ideas.")

    def content(self) -> str:
        follow = f" Follow-up ideas: {self.follow_ups}" if self.follow_ups else ""
        return f"Conversation thread about {self.topic}. Ask: \"{self.question}\".{follow}"

    def label(self) -> str:
        return self.topic


PlanStep = Annotated[Union[OpeningStep, NamesGameStep, PracticeStep, ActivityStep, GamesActivityStep, ThreadStep],
                     Field(discriminator="kind")]
BUILDABLE = (OpeningStep, NamesGameStep, PracticeStep, ActivityStep, GamesActivityStep, ThreadStep)

STEP_CLASSES = {cls.model_fields["kind"].default: cls for cls in BUILDABLE}


def min_answers(kind: str) -> int:
    """The fewest of his answers before a step of this kind may end (the follow-up and free
    conversation steps count as talking steps: 2)."""
    cls = STEP_CLASSES.get(kind)
    return cls.MIN_ANSWERS if cls else 2


# Handed out again and again once the planned steps run out, until the wrap-up note (~9 min) or
# "you may close" (after 8 min, 13). Never "the steps are done": that made her close at once.
FOLLOW_UP = ("Follow-up: go back to something he told you earlier today (a detail of his story, his opinion, what "
             "happened next) and talk about it with him for a few exchanges. Not a wrap-up question, not a summary.")

# The step without a plan (memory but no built plan yet).
FREE_CONVERSATION = ("Conversation: ask whether there is something special he'd like to talk about today; follow his "
                     "choice, one thread at a time, with follow-ups on his own words.")

NAMES = {"opening": "opening", "names_game": "names game", "practice": "practice", "activity": "activity",
         "games_activity": "game-linked activity", "thread": "conversation thread", "conversation": "conversation"}


def overview(steps: list[dict]) -> str:
    """For the system prompt: NOT the agenda. With a numbered list she saw where the plan ended and
    closed there herself (12.10, 5 minutes in); with the names in it she guessed the next question
    (12.10). She only needs to know that there is always a next step."""
    return ("There is always a next step: the app hands them out one at a time, for as long as the session "
            "lasts. You never know how many are left, and only the app ends the session.")


def tool_parameters(cls: type[Step]) -> dict:
    """The builder tool's JSON schema, from the class's content fields (kind and items excluded)."""
    props, required = {}, []
    for name, field in cls.model_fields.items():
        if name in ("kind", "items"):
            continue
        typ = {str: "string", bool: "boolean"}.get(field.annotation, "string")
        props[name] = {"type": typ, "description": field.description or ""}
        if field.is_required():
            required.append(name)
    return {"type": "object", "properties": props, "required": required}
