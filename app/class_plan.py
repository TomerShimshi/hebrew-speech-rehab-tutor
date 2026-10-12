"""Lesson plans (sub-plan 05): choosing the plan for a session and rendering it for the tutor."""

import re
from functools import lru_cache

import yaml

from app import check_in_set
from app.config import REPO_ROOT
from app.schemas import ClassPlan

INTRO_PLAN_PATH = REPO_ROOT / "prompts" / "intro_plan.yaml"


@lru_cache
def intro_plan() -> ClassPlan:
    """The fixed 'getting to know you' plan (no LLM)."""
    return ClassPlan(**yaml.safe_load(INTRO_PLAN_PATH.read_text(encoding="utf-8"))).tidy()


def with_names_game(plan: ClassPlan | None, current_set: dict | None) -> ClassPlan | None:
    """Today's names-game items from the stable set (12), in rotation, as the plan's check-in
    items -- never in an intro session. Without a set, a regular plan has no game today."""
    if plan is None or plan.plan_type == "intro":
        return plan
    chosen = check_in_set.choose_items(current_set)
    # Today's game names are not practiced again in the same session (12.10: a name asked twice).
    asked = {" ".join(c["target"].split()) for c in chosen}
    keep = lambda items: [p for p in items if " ".join(p.target.split()) not in asked]  # noqa: E731
    return plan.model_copy(update={"probe": check_in_set.probe_items(chosen), "practice": keep(plan.practice),
                                   "reserve_practice": keep(plan.reserve_practice)})


def plan_for_session(store, pid: str) -> ClassPlan | None:
    """The built plan if there is one; the intro plan for a brand-new (or reset) account;
    otherwise None -- the tutor then follows the generic structure. Never blocks."""
    raw = store.get_next_plan(pid)
    if raw:
        try:
            return ClassPlan(**raw)
        except Exception:  # noqa: BLE001 -- a malformed stored plan must not break a session
            pass
    memory = store.get_memory(pid)
    if not memory or not memory.get("memory_prompt"):
        return intro_plan()
    return None


HEBREW = re.compile(r"[\u0590-\u05FF]")
INDENT = "      "


def _field(label: str, value: str) -> str:
    """'label: value' -- but a Hebrew sentence goes on its own indented line, so English and
    Hebrew are never mixed in one line (easier for the family to read, same for the model)."""
    words = (value or "").split()
    hebrew = sum(1 for word in words if HEBREW.search(word))
    if hebrew > 2 and hebrew * 2 >= len(words):  # a Hebrew sentence (not English with a quoted phrase)
        return f"{label}:\n{INDENT}{value}"
    return f"{label}: {value}"


def _practice_lines(items) -> list[str]:
    lines = []
    for i, p in enumerate(items, 1):
        lines += [f"  {i}.", f"{INDENT}ask: {p.elicit}",
                  f"{INDENT}meaning: {p.hint_meaning}", f"{INDENT}first syllable: {p.hint_first_syllable}",
                  f"{INDENT}complete: {p.sentence_completion}", f"{INDENT}answer: {p.target}"]
    return lines


def plan_names(plan: ClassPlan | None) -> list[str]:
    """Every name today's session may ask for: the names game, practice and reserve (12b). They
    go into the transcription vocabulary -- short proper names are what it mishears most."""
    if plan is None:
        return []
    return list(dict.fromkeys(i.target for i in [*plan.probe, *plan.practice, *plan.reserve_practice]))


def render_class_plan(plan: ClassPlan | None, *, steps_mode: bool = False) -> str:
    """The TODAY'S PLAN section of the tutor's system instruction. In steps mode (13) the items she
    asks (names game, practice, activity, reserve, topics) come ONLY from the page, one step at a
    time: with them here she jumped ahead to the next question, and then asked it again."""
    if plan is None:
        return ""
    if steps_mode:
        plan = plan.model_copy(update={"probe": [], "practice": [], "reserve_practice": [], "reserve_topics": [],
                                       "activity": "", "games_link_activity": "", "conversation_topics": []})
    lines = [f"Plan type: {plan.plan_type}",
             f"Main goal ({plan.primary_goal.type.value}): {plan.primary_goal.description}"]
    if plan.recall_from_last_time:
        lines.append(_field("Recall from last time (one natural sentence in your greeting)", plan.recall_from_last_time))
    if plan.warmup:
        lines.append(_field("Warm-up", plan.warmup))
    if plan.probe:
        # The names game (12): its own short moment, run as the NAMES GAME rules say.
        lines.append("Names game (when the note to start it comes; each question word for word, NO hints):")
        for i, p in enumerate(plan.probe, 1):
            lines.append(f"  {i}.")
            if p.bridge:  # older plans' check-ins had a lead-in
                lines.append(f"{INDENT}lead-in: {p.bridge}")
            lines += [f"{INDENT}ask: {p.elicit}", f"{INDENT}answer: {p.target}"]
    if plan.practice:
        lines.append("Practice items (when he's stuck, hints in this order: meaning -> first syllable -> "
                     "sentence completion -> say it yourself and have him use it in a sentence):")
        lines += _practice_lines(plan.practice)
    if plan.activity:
        lines.append(_field("Activity", plan.activity))
    if plan.conversation_topics:
        lines.append("Conversation topics: " + "; ".join(plan.conversation_topics))
    if plan.homework:
        lines.append(_field("Homework (say it ONLY in the closing, after the wrap-up note)", plan.homework))
    if plan.game_homework:
        lines.append("Game homework to suggest in the closing (a button for it appears on his screen):")
        lines += [f"{INDENT}{g.name_he or g.game_id} -- {g.why}" for g in plan.game_homework]
    if plan.games_note:
        lines.append(_field("About his games", plan.games_note))
    if plan.games_link_activity:
        lines.append(_field("Game-linked activity (talking practice built on what he played)", plan.games_link_activity))
    if plan.reserve_practice or plan.reserve_topics:
        # 12b: so a fast conversation never runs out of material before the wrap-up note
        lines.append("RESERVE -- use ONLY if everything above is done and the wrap-up note hasn't come yet "
                     "(never a reason to close early):")
        if plan.reserve_practice:
            lines.append("  Extra practice items (same hint order):")
            lines += _practice_lines(plan.reserve_practice)
        if plan.reserve_topics:
            lines.append("  Extra threads: " + "; ".join(plan.reserve_topics))
    if plan.fatigue_fallback:
        lines.append(_field("If he is tired or frustrated", plan.fatigue_fallback))
    if plan.avoid:
        lines.append("Avoid: " + "; ".join(plan.avoid))
    return "\n".join(lines)
