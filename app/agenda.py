"""The session's agenda (sub-plan 13): TODAY'S PLAN as steps, run by the page.

The tutor gets one step at a time: the first in the start note, each next one in the reply to
her `next_step` tool call (handled by the page, static/app.js). The tool is blocking and called
FIRST: when his answer finishes a step she calls it before speaking, then says one turn -- her
reaction and the next step (live-tested 12.10.26). Plain code, no LLM.
"""

from app.schemas import ClassPlan

# Handed out again and again once the planned steps run out, until the wrap-up note (~9 min).
# Never "the steps are done": on 12.10 that phrase made her close at once.
FOLLOW_UP = ("Follow-up: go back to something he told you earlier today (a detail of his story, his "
             "opinion, what happened next) and talk about it with him for a few exchanges. Not a wrap-up "
             "question, not a summary.")


def _practice_text(i: int, n: int, p, label: str) -> str:
    topic = getattr(p, "topic", "") or "something from his life that this name fits"
    return (f"{label} {i} of {n}, inside a short conversation: talk with him about {topic} -- an open question, "
            f"follow his answer -- and at a natural point ask \"{p.elicit}\" (answer: {p.target}). If he's "
            f"stuck, hints one at a time: meaning \"{p.hint_meaning}\" -> first syllable "
            f"\"{p.hint_first_syllable}\" -> complete \"{p.sentence_completion}\" -> say it and have him use it "
            f"in a sentence. After the name, one follow-up about it. Then the step is finished.")


def build_agenda(plan: ClassPlan | None) -> list[dict]:
    """[{kind, label, text}] in order. `label` is a short name for the caregiver page."""
    steps = [{"kind": "opening", "label": "", "text": (
        "Opening: greet him warmly, ask how he feels and react to what he says (recall ONE thing from last "
        "time, ask about his games or homework, as the rules say). The step is finished after his answer "
        "and your reaction.")}]
    if plan is None:
        steps.append({"kind": "conversation", "label": "", "text": (
            "Conversation: ask whether there is something special he'd like to talk about today; follow his "
            "choice, one thread at a time.")})
        return steps
    if plan.probe:
        questions = " ".join(f"{i}) \"{p.elicit}\" (answer: {p.target})" for i, p in enumerate(plan.probe, 1))
        steps.append({"kind": "names_game", "label": "", "text": (
            f"Names game, {len(plan.probe)} questions, one at a time, word for word, NO hints: say "
            f"\"בוא נעשה משחק קצר של שמות: אני אתאר משהו, ואתה תגיד לי איך קוראים לזה.\", then {questions}. "
            f"If he doesn't find one, say the name warmly in one sentence and go on. The step is finished "
            f"only after his answer to the LAST question. (Skip it if he seems tired or low.)")})
    for i, p in enumerate(plan.practice, 1):
        steps.append({"kind": "practice", "label": p.target,
                      "text": _practice_text(i, len(plan.practice), p, "Practice item")})
    if plan.activity:
        steps.append({"kind": "activity", "label": "", "text": (
            f"Activity: {plan.activity} Give it time and let him complete it; the step is finished when he "
            f"has.")})
    if plan.games_link_activity:
        steps.append({"kind": "games_activity", "label": "", "text": (
            f"Game-linked activity: {plan.games_link_activity}")})
    for i, p in enumerate(plan.reserve_practice, 1):
        steps.append({"kind": "reserve", "label": p.target,
                      "text": _practice_text(i, len(plan.reserve_practice), p, "Extra practice item")})
    # then the plan's open threads, each its own step (a fast talker reaches them, 12b)
    for topic in [*plan.reserve_topics, *plan.conversation_topics]:
        steps.append({"kind": "thread", "label": "", "text": (
            f"Conversation thread: {topic} Ask about it with a concrete question, follow his answer with at least "
            f"one follow-up on his own words, and let him tell it fully before the step is finished.")})
    return steps


def after_last(plan: ClassPlan | None) -> str:
    """The step handed out once the planned ones run out (the same for every plan)."""
    return FOLLOW_UP


def overview(steps: list[dict]) -> str:
    """For the system prompt: the whole agenda, so she knows where she is going (stable across
    reconnects -- the current step itself only ever comes from the page)."""
    names = {"opening": "opening", "conversation": "conversation", "names_game": "names game",
             "practice": "practice", "activity": "activity", "games_activity": "game-linked activity",
             "reserve": "extra practice", "thread": "conversation thread"}
    parts = []
    for i, s in enumerate(steps, 1):
        name = names.get(s["kind"], s["kind"])
        parts.append(f"{i}. {name} ({s['label']})" if s["label"] else f"{i}. {name}")
    return "Today's steps, in order: " + ", ".join(parts) + "."
