"""Lesson plans: choosing the plan for a session (05), preparing its steps at session start
(12, 13.5), and rendering it -- for the tutor (the session-level parts) and in full (the
caregiver page, the memory agent)."""

import re
from functools import lru_cache

import yaml

from app import check_in_set
from app.config import REPO_ROOT
from app.schemas import ClassPlan
from app.steps import FREE_CONVERSATION, NamesGameStep, OpeningStep, PracticeStep

INTRO_PLAN_PATH = REPO_ROOT / "prompts" / "intro_plan.yaml"


@lru_cache
def intro_plan() -> ClassPlan:
    """The fixed 'getting to know you' plan (no LLM)."""
    return ClassPlan(**yaml.safe_load(INTRO_PLAN_PATH.read_text(encoding="utf-8")))


def plan_for_session(store, pid: str) -> ClassPlan | None:
    """The built plan if there is one; the intro plan for a brand-new (or reset) account;
    otherwise None -- a free conversation. Never blocks. A plan saved before 13.5 (no steps) counts
    as no plan: it is rebuilt."""
    raw = store.get_next_plan(pid)
    if raw and raw.get("steps"):
        try:
            return ClassPlan(**raw)
        except Exception:  # noqa: BLE001 -- a malformed stored plan must not break a session
            pass
    memory = store.get_memory(pid)
    if not memory or not memory.get("memory_prompt"):
        return intro_plan()
    return None


def _norm(text: str) -> str:
    return " ".join((text or "").split())


def prepare_for_session(plan: ClassPlan | None, current_set: dict | None) -> ClassPlan | None:
    """What can only be decided at session start (12, 13): the names game's names from the stable
    set, in rotation, at the place the builder chose (no set or an intro -> no game); today's game
    names out of the practice steps (a name asked twice, 12.10); an opening first."""
    if plan is None:
        return None
    chosen = [] if plan.plan_type == "intro" else check_in_set.choose_items(current_set)
    asked = {_norm(c["target"]) for c in chosen}
    steps = []
    for step in plan.steps:
        if isinstance(step, NamesGameStep):
            if chosen:
                steps.append(step.model_copy(update={"items": check_in_set.probe_items(chosen)}))
        elif isinstance(step, PracticeStep) and _norm(step.name) in asked:
            continue
        else:
            steps.append(step)
    if not steps or not isinstance(steps[0], OpeningStep):
        steps = [OpeningStep(), *[s for s in steps if not isinstance(s, OpeningStep)]]
    return plan.model_copy(update={"steps": steps})


def session_steps(plan: ClassPlan | None) -> list[dict]:
    """The steps the page hands out: kind, a short label, and the exact instruction."""
    steps = plan.steps if plan else [OpeningStep()]
    out = [{"kind": s.kind, "label": s.label(), "text": s.instruction(),
            **({"cards": s.cards()} if hasattr(s, "cards") and s.cards() else {})} for s in steps]
    if plan is None:
        out.append({"kind": "conversation", "label": "", "text": FREE_CONVERSATION})
    return out


def plan_names(plan: ClassPlan | None) -> list[str]:
    """Every name today's session may ask for (the names game, practice): they go into the
    transcription vocabulary -- short proper names are what it mishears most (12b)."""
    if plan is None:
        return []
    return list(dict.fromkeys(n for s in plan.steps for n in s.names()))


HEBREW = re.compile(r"[֐-׿]")
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
    """The TODAY'S PLAN section of the tutor's system instruction: the session-level parts only.
    The steps come from the page, one at a time (13): with them here she jumped ahead."""
    if plan is None:
        return ""
    lines = [f"Plan type: {plan.plan_type}",
             f"Main goal ({plan.primary_goal.type.value}): {plan.primary_goal.description}"]
    if plan.homework:
        lines.append(_field("Homework (say it ONLY in the closing, after the wrap-up note)", plan.homework))
    if plan.game_homework:
        lines.append("Game homework to suggest in the closing (a button for it appears on his screen):")
        lines += [f"{INDENT}{g.name_he or g.game_id} -- {g.why}" for g in plan.game_homework]
    if plan.games_note:
        lines.append(_field("About his games", plan.games_note))
    if plan.fatigue_fallback:
        lines.append(_field("If he is tired or frustrated", plan.fatigue_fallback))
    if plan.avoid:
        lines.append("Avoid: " + "; ".join(plan.avoid))
    return "\n".join(lines)


def render_plan_full(plan: ClassPlan | None) -> str:
    """The whole plan, steps included -- for the caregiver page and the memory agent."""
    if plan is None:
        return ""
    lines = [render_class_plan(plan)]
    if plan.estimated_minutes:
        lines.append(f"Estimated length: ~{plan.estimated_minutes:.1f} minutes at his pace")
    lines.append("Steps:")
    for i, step in enumerate(plan.steps, 1):
        lines.append(f"  {i}. {step.content()}")
    return "\n".join(lines)
