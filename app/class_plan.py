"""Lesson plans (sub-plan 05): choosing the plan for a session and rendering it for the tutor."""

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


def render_class_plan(plan: ClassPlan | None) -> str:
    """The TODAY'S PLAN section of the tutor's system instruction."""
    if plan is None:
        return ""
    lines = [f"Plan type: {plan.plan_type}",
             f"Main goal ({plan.primary_goal.type.value}): {plan.primary_goal.description}"]
    if plan.recall_from_last_time:
        lines.append(f"Recall from last time (one natural sentence in your greeting): {plan.recall_from_last_time}")
    if plan.warmup:
        lines.append(f"Warm-up: {plan.warmup}")
    if plan.probe:
        lines.append("Check-in items -- ask each one WITHOUT any hint first and give him real time; "
                     "only after a genuine attempt use the hint ladder. Never call this a test:")
        lines += [
            f"  {i}. ({p.kind}) " + (f"lead-in: {p.bridge} | " if p.bridge else "") + f"ask: {p.elicit} -> answer: {p.target}"
            for i, p in enumerate(plan.probe, 1)
        ]
    if plan.practice:
        lines.append("Practice items (when he's stuck, hints in this order: meaning -> first syllable -> "
                     "sentence completion -> say it yourself and have him use it in a sentence):")
        lines += [
            f"  {i}. {p.target}: ask: {p.elicit} | meaning: {p.hint_meaning} | "
            f"first syllable: {p.hint_first_syllable} | complete: {p.sentence_completion}"
            for i, p in enumerate(plan.practice, 1)
        ]
    if plan.activity:
        lines.append(f"Activity: {plan.activity}")
    if plan.conversation_topics:
        lines.append("Conversation topics: " + "; ".join(plan.conversation_topics))
    if plan.homework:
        lines.append(f"Homework to give at the end: {plan.homework}")
    if plan.game_homework:
        lines.append("Game homework to suggest in the closing (a button for it appears on his screen): " + "; ".join(
            f"{g.name_he or g.game_id} -- {g.why}" for g in plan.game_homework))
    if plan.games_note:
        lines.append(f"About his games: {plan.games_note}")
    if plan.games_link_activity:
        lines.append(f"Game-linked activity (talking practice built on what he played): {plan.games_link_activity}")
    if plan.fatigue_fallback:
        lines.append(f"If he is tired or frustrated: {plan.fatigue_fallback}")
    if plan.avoid:
        lines.append("Avoid: " + "; ".join(plan.avoid))
    return "\n".join(lines)
