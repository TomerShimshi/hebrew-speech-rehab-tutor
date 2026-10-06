"""Lesson plans (sub-plan 05): choosing the plan for a session and rendering it for the tutor."""

import re
from functools import lru_cache

import yaml

from app.config import REPO_ROOT
from app.schemas import ClassPlan

INTRO_PLAN_PATH = REPO_ROOT / "prompts" / "intro_plan.yaml"


@lru_cache
def intro_plan() -> ClassPlan:
    """The fixed 'getting to know you' plan (no LLM)."""
    return ClassPlan(**yaml.safe_load(INTRO_PLAN_PATH.read_text(encoding="utf-8"))).tidy()


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


def render_class_plan(plan: ClassPlan | None) -> str:
    """The TODAY'S PLAN section of the tutor's system instruction."""
    if plan is None:
        return ""
    lines = [f"Plan type: {plan.plan_type}",
             f"Main goal ({plan.primary_goal.type.value}): {plan.primary_goal.description}"]
    if plan.recall_from_last_time:
        lines.append(_field("Recall from last time (one natural sentence in your greeting)", plan.recall_from_last_time))
    if plan.warmup:
        lines.append(_field("Warm-up", plan.warmup))
    if plan.probe:
        lines.append("Check-in items -- ask each one WITHOUT any hint first and give him real time; "
                     "only after a genuine attempt use the hint ladder. Never call this a test:")
        for i, p in enumerate(plan.probe, 1):
            # in the order she says it: lead-in, question -- then the answer he should find
            lines.append(f"  {i}. ({p.kind})")
            if p.bridge:
                lines.append(f"{INDENT}lead-in: {p.bridge}")
            lines += [f"{INDENT}ask: {p.elicit}", f"{INDENT}answer: {p.target}"]
    if plan.practice:
        lines.append("Practice items (when he's stuck, hints in this order: meaning -> first syllable -> "
                     "sentence completion -> say it yourself and have him use it in a sentence):")
        for i, p in enumerate(plan.practice, 1):
            lines += [f"  {i}.", f"{INDENT}ask: {p.elicit}",
                      f"{INDENT}meaning: {p.hint_meaning}", f"{INDENT}first syllable: {p.hint_first_syllable}",
                      f"{INDENT}complete: {p.sentence_completion}", f"{INDENT}answer: {p.target}"]
    if plan.activity:
        lines.append(_field("Activity", plan.activity))
    if plan.conversation_topics:
        lines.append("Conversation topics: " + "; ".join(plan.conversation_topics))
    if plan.homework:
        lines.append(_field("Homework to give at the end", plan.homework))
    if plan.game_homework:
        lines.append("Game homework to suggest in the closing (a button for it appears on his screen):")
        lines += [f"{INDENT}{g.name_he or g.game_id} -- {g.why}" for g in plan.game_homework]
    if plan.games_note:
        lines.append(_field("About his games", plan.games_note))
    if plan.games_link_activity:
        lines.append(_field("Game-linked activity (talking practice built on what he played)", plan.games_link_activity))
    if plan.fatigue_fallback:
        lines.append(_field("If he is tired or frustrated", plan.fatigue_fallback))
    if plan.avoid:
        lines.append("Avoid: " + "; ".join(plan.avoid))
    return "\n".join(lines)
