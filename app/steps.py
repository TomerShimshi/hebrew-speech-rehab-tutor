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

from typing import Annotated, ClassVar, Literal, Union, get_args, get_origin

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
        return f"{self.content()} HOW: {self.rules()} {FINISHED}"

    def rules(self) -> str:
        return self.RULES

    def answers_needed(self) -> int:
        """The fewest of his answers before the page lets this step end."""
        return self.MIN_ANSWERS


class OpeningStep(Step):
    kind: Literal["opening"] = "opening"
    TOOL: ClassVar[str] = "set_opening"
    GUIDE: ClassVar[str] = ("The opening (always the first step). recall: ONE sentence she can use in her greeting, "
                            "recalling something from last time (from the memory). opener: an easy, pleasant question "
                            "at his level. Both in HEBREW, in her voice (a woman; masculine for him).")
    RULES: ClassVar[str] = ("Greet him warmly, ask how he feels and react to what he says (recall ONE thing from last "
                            "time, ask about his games or homework, as the rules say). If he shares something -- news, "
                            "a feeling, something that happened today -- stay with it for a few exchanges before "
                            "anything else: that is the conversation.")
    MINUTES: ClassVar[float] = 0.6
    MIN_ANSWERS: ClassVar[int] = 2
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
                            "talk, and for a fast talker. Never about the homework: the opening already asks about it.")
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


class SequencingStep(Step):
    """Telling things in order (14): his therapist's kind of task, by voice. One right order."""
    kind: Literal["sequencing"] = "sequencing"
    TOOL: ClassVar[str] = "add_sequencing"
    GUIDE: ClassVar[str] = (
        "A sequencing task -- telling things in order, as his speech therapist practices with him. task: "
        "'scrambled' (she says the events out of order, he tells the story in the right order) or 'retell' (she "
        "tells a short story, he retells it in order); rotate them. events: the story's events in HEBREW, in the "
        "CORRECT order, one short, simple sentence each, about 'him' (a man) or 'her' -- a NEW everyday, adult "
        "situation (a visit to the doctor, buying a gift, fixing a leaking tap, a bus ride), never from his own "
        "life, with events that can only come in one order. Exactly the number of events HIS SEQUENCING "
        "recommends (+-1). Code scrambles them.")
    RULES: ClassVar[str] = (
        "This is the one long turn of the session: introduce it lightly as a game (scrambled: \"אספר לך כמה דברים "
        "שקרו, אבל בבלגן, ואתה תספר לי את הסיפור לפי הסדר\"; retell: tell the story, then \"ספר לי את הסיפור "
        "במילים שלך, מההתחלה\"), then say all the events in ONE turn, slowly, one short sentence each with a small "
        "pause between them, and only then ask your one question. In the scrambled game, number them as you say "
        "them (\"ראשון: ... שני: ...\") -- each one appears on his screen as a card as you say it, so you may say "
        "\"הם גם מופיעים לך על המסך\". Let him tell it ALL the way through without "
        "correcting him; repeat all the events once if he asks. If the order is off, help with ONE question at a "
        "time (\"מה קרה קודם, ... או ...?\") -- never the answer first -- and say warmly what he got right. Then "
        "link the story to his life (\"קרה לך פעם משהו כזה?\") for an exchange or two. Skip it, without "
        "mentioning it, if he seems tired.")
    MINUTES: ClassVar[float] = 2.5
    MIN_MINUTES: ClassVar[float] = 2.0
    MIN_ANSWERS: ClassVar[int] = 2
    task: Literal["scrambled", "retell"] = Field(description="'scrambled' or 'retell'.")
    title: str = Field(description="ENGLISH: a short title for the family, e.g. 'buying a gift'.")
    events: list[str] = Field(description="HEBREW: the events in the CORRECT order, one short sentence each.")
    told_order: list[int] = []  # filled by code when it's added: the order she says them in (scrambled)

    def content(self) -> str:
        numbered = " ".join(f'{i}) "{e}"' for i, e in enumerate(self.events, 1))
        if self.task == "retell":
            return f"Story retell ({self.title}): tell him this story, in this order: {numbered}."
        order = ", ".join(str(i) for i in self.told_order)
        return (f"Sequencing game ({self.title}): the events, numbered in the CORRECT order: {numbered}. Say them "
                f"to him in THIS scrambled order: {order}.")

    def label(self) -> str:
        return self.title

    def cards(self) -> list[str]:
        """The scrambled game's events in the order she says them, shown on his screen as she says
        each one (13.10: by ear it was hard to remember them). Never for a retell -- that's from memory."""
        if self.task != "scrambled":
            return []
        return [self.events[i - 1] for i in self.told_order if 1 <= i <= len(self.events)]


# ---- the needs check of a new account's first two sessions (15.5) ------------------------------
# Like a speech therapist's first meeting, but inside "getting to know you": a few small checks
# between ordinary talk. Not a test and never called one; not a diagnosis. Only in the fixed
# first-sessions plans (prompts/intro_needs_*.yaml), never built by the plan builder.
CHECK_AREAS = ("conversation", "naming", "repetition", "understanding", "connected_speech", "clarity", "goals")
CHECK_COMMON = ("Bring it in lightly, as part of the conversation -- never say test, check or exercise. Whatever "
                "happens, react warmly; never say it was wrong. If something doesn't come after a few seconds, help "
                "gently (the first sound, then the word) and move on. Don't comment on how he did.")
CHECK_RULES = {
    "naming": ("A short riddle game (\"בוא נשחק רגע בחידות\"): describe each thing in ITEMS, one at a time, and let "
               "him say what it is (the answer is after the '='; never say it first)."),
    "repetition": ("Playfully ask him to say after you (\"תגיד אחריי\"): each item in ITEMS in turn -- a word, a "
                   "phrase, a longer sentence. Say each once, clearly; say it again only if he asks."),
    "understanding": ("Ask the first item as a light riddle he answers yes or no; later, ask the second item "
                      "naturally, as one two-part request. Don't repeat or simplify unless he asks."),
    "connected_speech": ("Ask him to explain the first item step by step, as if to someone who has never done it. "
                         "Let him tell it all the way; if he stops early, one \"ומה אחר כך?\". No corrections."),
    "clarity": ("Ask him to say each item after you, clearly. If the item is \"פה-טה-קה\", make it a playful moment "
                "instead (\"בוא ננסה משהו מצחיק\"): as fast as he can, a few times, with him, laughing lightly."),
    "goals": ("Ask what is hardest for him when he talks with people; listen and react. Only after his answer, "
              "ask what he would like to be able to do better. Never say goals or assessment."),
}
CHECK_ANSWERS = {"naming": 3, "repetition": 3, "understanding": 2, "connected_speech": 1, "clarity": 1, "goals": 2}


class CheckStep(Step):
    kind: Literal["check"] = "check"
    MINUTES: ClassVar[float] = 1.0
    area: Literal["naming", "repetition", "understanding", "connected_speech", "clarity", "goals"]
    items: list[str] = []  # HEBREW: what she says (a riddle = its answer, a phrase to repeat, a request)

    def content(self) -> str:
        items = " ".join(f'{i}) "{x}"' for i, x in enumerate(self.items, 1))
        return f"A short {self.area.replace('_', ' ')} moment, inside the conversation." + (
            f" ITEMS: {items}." if items else "")

    def rules(self) -> str:
        return f"{CHECK_RULES[self.area]} {CHECK_COMMON}"

    def answers_needed(self) -> int:
        return CHECK_ANSWERS[self.area]

    def label(self) -> str:
        return self.area


class SummaryStep(Step):
    """Summarizing a short text in his own words (17; ARCS-style, by voice). Takes turns with the
    sequencing task, session by session."""
    kind: Literal["summary"] = "summary"
    TOOL: ClassVar[str] = "add_summary"
    GUIDE: ClassVar[str] = (
        "A summarizing task (ARCS-style, as in mild aphasia therapy): she reads him a short paragraph, he tells "
        "it in his own words. paragraph: simple, natural HEBREW, 3-5 short sentences, on something he cares about "
        "(technology, a place, a podcast or news topic -- from his interests), NEVER from his private life, with "
        "no rare words. main_ideas: its main ideas in ENGLISH, one per item, in order -- exactly the number HIS "
        "SUMMARIZING recommends (+-1); each must be stated in the paragraph. Only when HIS DISCOURSE TASK says it's "
        "a summary's turn.")
    RULES: ClassVar[str] = (
        "Introduce it lightly (\"אקריא לך משהו קצר, ואחר כך תספר לי במילים שלך מה שמעת\"), then read the "
        "paragraph in ONE turn, slowly and clearly, and only then ask him to tell it in his own words. Let him tell "
        "it ALL the way without correcting him or filling in; read it again once only if he asks. Then react "
        "warmly to what he told, and ask ONE question about his opinion of it, for an exchange or two. Never "
        "quiz him on details. Skip it, without mentioning it, if he seems tired.")
    MINUTES: ClassVar[float] = 2.5
    MIN_MINUTES: ClassVar[float] = 2.0
    MIN_ANSWERS: ClassVar[int] = 2
    title: str = Field(description="ENGLISH: a short title for the family, e.g. 'a new train line'.")
    paragraph: str = Field(description="HEBREW: the paragraph she reads, 3-5 short sentences.")
    main_ideas: list[str] = Field(description="ENGLISH: the paragraph's main ideas, in order, one per item.")

    def content(self) -> str:
        ideas = " ".join(f"{i}) {x}" for i, x in enumerate(self.main_ideas, 1))
        return f"Summarizing ({self.title}): read him this paragraph: \"{self.paragraph}\" (its main ideas: {ideas})."

    def label(self) -> str:
        return self.title


class StoryProbeStep(Step):
    """The connected-speech probe (17): a fixed short story he retells, asked the same way every time.
    Placed by code (app/probes.py), never by the plan builder."""
    kind: Literal["story_probe"] = "story_probe"
    RULES: ClassVar[str] = (
        "Say lightly that you have a very short story for him (\"יש לי סיפור קצר בשבילך\"), tell it EXACTLY as "
        "written, slowly, in one turn, then ask: \"ספר לי את הסיפור במילים שלך\". Let him tell it all the way: no "
        "help, no hints, no questions about details, don't tell it again. Then react to the STORY itself, warmly, "
        "like a person who enjoyed it (\"איזה סיפור -- המפתחות במקרר!\") -- never count or grade what he "
        "remembered -- and ask ONE short question linking it to his life (\"גם לך קרה פעם ש...?\"). The step is "
        "finished after his answer to that.")
    MINUTES: ClassVar[float] = 2.0
    # 2: the retelling, then the link to his life -- with 1 she moved on without a word about his story (21.10)
    MIN_ANSWERS: ClassVar[int] = 2
    story_id: str
    title: str
    story: str  # HEBREW, told exactly
    main_ideas: list[str]  # ENGLISH, in order

    def content(self) -> str:
        ideas = " ".join(f"{i}) {x}" for i, x in enumerate(self.main_ideas, 1))
        return f"A short story to retell ({self.title}). Tell it exactly: \"{self.story}\" (its main ideas: {ideas})."

    def label(self) -> str:
        return self.title


class _MissingAreaStep(Step):
    """Practice in an area the app practices only once a difficulty is confirmed (17.5). Offered to the
    builder only for the area whose turn it is, at its level (HIS PROGRESS)."""
    MINUTES: ClassVar[float] = 1.5
    MIN_MINUTES: ClassVar[float] = 1.0
    MIN_ANSWERS: ClassVar[int] = 3
    items: list[str] = Field(description="HEBREW: the items she says, in order (3-6), at his level.")

    def content(self) -> str:
        items = " ".join(f'{i}) "{x}"' for i, x in enumerate(self.items, 1))
        return f"{self.NAME} practice. ITEMS: {items}."


class RepetitionStep(_MissingAreaStep):
    kind: Literal["repetition"] = "repetition"
    NAME: ClassVar[str] = "Repetition"
    TOOL: ClassVar[str] = "add_repetition"
    GUIDE: ClassVar[str] = (
        "Repetition practice (only when HIS PROGRESS gives repetition this session): 3-6 items he says after her, "
        "built from HIS topics, at the length his level says (words -> phrases -> sentences). HEBREW, everyday "
        "words, no names he might not know.")
    RULES: ClassVar[str] = (
        "Lightly, as a game (\"בוא ננסה משהו: אני אגיד, ואתה תגיד אחריי\"): say each item once, clearly, and let him "
        "repeat it. If it didn't come out, one more try together; then a warm reaction and the next -- never "
        "\"wrong\". After the last, a short word on how it went, without counting.")


class UnderstandingStep(_MissingAreaStep):
    kind: Literal["understanding"] = "understanding"
    NAME: ClassVar[str] = "Understanding"
    TOOL: ClassVar[str] = "add_understanding"
    GUIDE: ClassVar[str] = (
        "Understanding practice (only when HIS PROGRESS gives understanding this session): 3-6 items at his level -- "
        "yes/no questions about his world, then spoken requests in two or three parts ('ספר לי X, ואחר כך Y'). "
        "HEBREW. Voice only: nothing to point at or do.")
    RULES: ClassVar[str] = (
        "Ask the items one at a time, each as part of the talk, and wait for his answer. If he got it wrong or "
        "only part of a request, say it again once, slowly, without saying he was wrong; then go on warmly.")


class ClarityStep(_MissingAreaStep):
    kind: Literal["clarity"] = "clarity"
    NAME: ClassVar[str] = "Speech clarity"
    TOOL: ClassVar[str] = "add_clarity"
    GUIDE: ClassVar[str] = (
        "Clarity practice (only when HIS PROGRESS gives clarity this session): 3-6 short phrases from his life, said "
        "with ONE cue the plan names (slower / louder / every sound) -- the cue that helped him before. HEBREW.")
    RULES: ClassVar[str] = (
        "Explain the one cue simply (e.g. \"בוא נגיד את זה לאט ובבירור\"), say each phrase, and let him say it "
        "with the cue. Praise the effort; one more try only if he wants. Never imitate or correct his sounds.")


class AreaProbeStep(Step):
    """The measurement of a practiced area on its fixed bank (17.5), placed by code, asked the same way."""
    kind: Literal["area_probe"] = "area_probe"
    MINUTES: ClassVar[float] = 1.5
    MIN_ANSWERS: ClassVar[int] = 4
    area: Literal["repetition", "understanding", "clarity"]
    items: list[str]  # HEBREW, asked exactly
    RULES: ClassVar[str] = (
        "A short game, asked exactly as written, one item at a time, waiting for each answer: for repetition and "
        "clarity he says each item after you; for understanding he answers each question or request. No hints, "
        "no second try, no saying if it was right -- a warm word after each, and go on.")

    def content(self) -> str:
        items = " ".join(f'{i}) "{x}"' for i, x in enumerate(self.items, 1))
        return f"A short {self.area} game (the same every time). ITEMS: {items}."

    def label(self) -> str:
        return self.area


class ViewStep(Step):
    """His own view (17): every ~2 weeks, one short question near the end. Placed by code."""
    kind: Literal["his_view"] = "his_view"
    RULES: ClassVar[str] = (
        "Ask him, simply and warmly: \"איך היה לך לדבר עם אנשים בשבוע האחרון?\" Listen; one follow-up on his own "
        "words (what was easier, what was harder), and react to it. No scale, no numbers, never a test.")
    MINUTES: ClassVar[float] = 1.0
    # 2: his answer, then the follow-up -- with 1 she moved on without reacting to it (21.10)
    MIN_ANSWERS: ClassVar[int] = 2

    def content(self) -> str:
        return "His own view of how talking is going."

    def label(self) -> str:
        return "his view"


PlanStep = Annotated[Union[OpeningStep, NamesGameStep, PracticeStep, ActivityStep, GamesActivityStep, ThreadStep,
                           SequencingStep, SummaryStep, CheckStep, StoryProbeStep, ViewStep, RepetitionStep,
                           UnderstandingStep, ClarityStep, AreaProbeStep], Field(discriminator="kind")]
BUILDABLE = (OpeningStep, NamesGameStep, PracticeStep, ActivityStep, GamesActivityStep, ThreadStep, SequencingStep,
             SummaryStep)

MISSING_AREA_STEPS = {"repetition": RepetitionStep, "understanding": UnderstandingStep, "clarity": ClarityStep}
STEP_CLASSES = {cls.model_fields["kind"].default: cls for cls in (*BUILDABLE, CheckStep, StoryProbeStep, ViewStep,
                                                                    *MISSING_AREA_STEPS.values(), AreaProbeStep)}


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

NAMES = {"repetition": "repetition", "understanding": "understanding", "clarity": "clarity",
         "area_probe": "a short measuring game", "story_probe": "a story to retell", "his_view": "his own view", "summary": "summarizing", "check": "getting-to-know check", "sequencing": "telling things in order", "opening": "opening", "names_game": "names game", "practice": "practice", "activity": "activity",
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
        if name in ("kind", "items", "told_order"):  # set by code, never by the builder
            continue
        if field.annotation == list[str]:
            props[name] = {"type": "array", "items": {"type": "string"}, "description": field.description or ""}
        elif get_origin(field.annotation) is Literal:
            props[name] = {"type": "string", "enum": list(get_args(field.annotation)),
                           "description": field.description or ""}
        else:
            typ = {str: "string", bool: "boolean"}.get(field.annotation, "string")
            props[name] = {"type": typ, "description": field.description or ""}
        if field.is_required():
            required.append(name)
    return {"type": "object", "properties": props, "required": required}
