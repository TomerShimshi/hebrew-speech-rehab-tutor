"""Test helpers for 13.5 plans: a ready-made plan of steps, and the plan builder's scripted tool
calls (the fake model "builds" a plan step by step, as the real one does)."""

from app.schemas import ClassPlan
from fake_llm import text, tool_calls


def practice(name="כנרת", topic="trips up north", about=False, question=None):
    return {"topic": topic, "name": name, "question": question or f"איך נקרא {name}?",
            "hint_meaning": "מקום יפה", "hint_first_syllable": "כִּ...", "hint_complete": f"בקיץ נסענו ל...",
            "about_his_life": about}


def thread(topic="his garden", question="מה אתה מגדל בגינה?"):
    return {"topic": topic, "question": question, "follow_ups": "Which plant is his favourite."}


def a_plan(*, steps=None, goal="name_retrieval", **over) -> ClassPlan:
    """A built plan (as saved): opening, names game, two practice names, an activity, a thread."""
    fields = dict(
        plan_type="regular",
        primary_goal={"type": goal, "description": "Names of places he loves."},
        steps=steps if steps is not None else [
            {"kind": "opening", "recall": "בפעם הקודמת סיפרת לי על הטיול לגליל."},
            {"kind": "names_game"},
            {"kind": "practice", **practice("כנרת")},
            {"kind": "practice", **practice("טבריה", topic="the Sea of Galilee")},
            {"kind": "activity", "instructions": "Ask him to describe the trip, step by step.", "why": "Discourse."},
            {"kind": "thread", **thread()},
        ],
        homework="Think of a place to tell me about.", fatigue_fallback="Talk about his garden.",
        avoid=["politics"],
    )
    fields.update(over)
    return ClassPlan(**fields)


SEQUENCE = {"task": "scrambled", "title": "buying a gift",
            "events": ["הוא יצא מהבית", "הוא נכנס לחנות", "הוא בחר מתנה", "הוא שילם בקופה"]}


def build_calls(*, goal="name_retrieval", names=("כנרת", "טבריה"), game=False, extra=(), finish=True,
                sequencing=True):
    """The tool calls of a typical, complete plan (~12 minutes with the default step lengths),
    with a sequencing task (14) -- required while he has no sequencing history."""
    calls = [("set_goal", {"type": goal, "description": "Names of places he loves."}),
             ("set_opening", {"recall": "בפעם הקודמת סיפרת לי על הגליל.", "opener": "איך אתה מרגיש היום?"})]
    if game:
        calls.append(("place_names_game", {}))
    calls += [("add_practice", practice(n)) for n in names]
    calls += [("add_activity", {"instructions": "Ask him to tell a trip in order.", "why": "Discourse."}),
              ("add_thread", thread()), ("add_thread", thread("his work", "ספר לי על העבודה שלך?")),
              ("add_thread", thread("music", "איזו מוזיקה אתה אוהב?")),
              ("add_thread", thread("his town", "מה אתה הכי אוהב בשכונה שלך?")),
              ("add_thread", thread("cooking", "מה אתה אוהב לבשל?")),
              *([("add_sequencing", SEQUENCE)] if sequencing else []),
              *extra,
              ("set_closing", {"homework": "Think of a place.", "fatigue_fallback": "His garden.", "avoid": []})]
    if finish:
        calls.append(("finish", {"notes_applied": ""}))
    return calls


def builder_rounds(*args, **kwargs):
    """The fake model's replies for one plan build: all the tool calls in one round, then a note."""
    return [tool_calls(*build_calls(*args, **kwargs)), text("done")]


def plan_context(client) -> str:
    """The context the plan builder's tool loop got (its first request; the research phase, which
    sees the same context, has another system instruction)."""
    for req in client.requests:
        if "YOU BUILD THE PLAN WITH TOOLS" in (req["config"].system_instruction or ""):
            return req["contents"][0].parts[0].text
    raise AssertionError("the plan builder never ran")
