"""Next-class builder (SUMMARY_MODEL call #3): updated memory -> the next session's ClassPlan.

One structured-output call (no tool loop): its inputs are small, so they all go in the
context, and its single output is a validated plan. Runs right after a successful memory
update (and from the hourly sweep). Never raises: failures are recorded as plan_status.
"""

import datetime as dt
import sys
from functools import lru_cache

import yaml
from google.genai import types

from app import word_bank
from app.agent.memory_update import format_memory
from app.config import REPO_ROOT, Settings
from app.games import render_games_for_plan
from app.llm import generate
from app.schemas import ClassPlan, MemoryDoc
from app.store import PLAN_DONE, PLAN_FAILED, SessionStore

PROMPT_PATH = REPO_ROOT / "prompts" / "next_class.yaml"
TECHNIQUES_PATH = REPO_ROOT / "prompts" / "therapy_techniques.yaml"
MIN_PROBE_ITEMS = 3


def _log(message: str) -> None:
    print(f"[next_class] {message}", file=sys.stderr, flush=True)


@lru_cache
def load_prompt() -> dict:
    return yaml.safe_load(PROMPT_PATH.read_text(encoding="utf-8"))


@lru_cache
def techniques_text() -> str:
    return TECHNIQUES_PATH.read_text(encoding="utf-8")


def _norm(word: str) -> str:
    return " ".join(word.split()).strip()


def _models(settings: Settings) -> list[str]:
    fallbacks = [m.strip() for m in settings.summary_fallback_models.split(",") if m.strip()]
    return [settings.summary_model, *fallbacks]


def _recent_plans_text(plans: list[dict]) -> str:
    if not plans:
        return "(no previous plans)"
    lines = []
    for p in plans:  # newest first
        goal = p.get("primary_goal") or {}
        lines.append(f"- {goal.get('type')}: {goal.get('description', '')[:160]}")
    return "\n".join(lines)


def build_context(memory_raw: dict, recent_plans: list[dict], profile_text: str, today: dt.date,
                  games_text: str = "(no games account linked)") -> str:
    memory = MemoryDoc(**memory_raw)
    due = word_bank.due_words(memory.word_bank, today)
    bank = ", ".join(
        f"{w} (last: {s.last_result.value if s.last_result else '?'}, next due {s.next_due})"
        for w, s in list(memory.word_bank.items())[-25:]
    ) or "(empty)"
    recent = "\n".join(f"- {r.get('date')}: mood {r.get('mood')}; {r.get('summary')}"
                       for r in memory_raw.get("recent_summaries", [])) or "(none)"
    return (
        f"# TODAY\n{today.isoformat()} ({today.strftime('%A')})\n\n"
        f"# PATIENT PROFILE\n{profile_text or '(none)'}\n\n"
        f"# MEMORY (what the tutor knows about him)\n{memory.memory_prompt}\n\n"
        f"# MEMORY SECTIONS\n{format_memory(memory)}\n\n"
        f"# FOCUS POINTS FROM THE LAST SESSION\n" + ("\n".join(f"- {f}" for f in memory.focus_next_session) or "(none)") + "\n\n"
        f"# WORD BANK\ndue for practice today: {', '.join(due) or '(none)'}\nall recent: {bank}\n\n"
        f"# RECENT SESSIONS (oldest first)\n{recent}\n\n"
        f"# RECENT PLANS' GOALS (newest first)\n{_recent_plans_text(recent_plans)}\n\n"
        f"# GAMES (the Simon games app; trends computed from his real data)\n{games_text}\n\n"
        f"# TECHNIQUES YOU MAY USE\n{techniques_text()}"
    )


def build_next_plan(
    store: SessionStore,
    client,
    settings: Settings,
    pid: str,
    sid: str,
    *,
    profile_text: str = "",
    today: dt.date | None = None,
    generate_fn=generate,
    games=None,  # a GamesSnapshot for his Simon profile (06), or None
) -> str:
    """Builds and saves the next plan after session `sid`. Returns the plan_status."""
    today = today or dt.date.today()
    try:
        memory_raw = store.get_memory(pid)
        if not memory_raw or not memory_raw.get("memory_prompt"):
            # Nothing to build on: the next session will be the intro plan.
            store.update_session(pid, sid, {"plan_status": PLAN_DONE, "plan_model": None})
            return PLAN_DONE
        context = build_context(memory_raw, store.recent_session_plans(pid, 5), profile_text, today,
                                games_text=render_games_for_plan(games))
        result = generate_fn(
            client, _models(settings), context,
            types.GenerateContentConfig(
                system_instruction=load_prompt()["system"],
                response_mime_type="application/json",
                response_schema=ClassPlan,
                temperature=0.4,
            ),
        )
        plan = result.response.parsed
        if not isinstance(plan, ClassPlan):
            plan = ClassPlan.model_validate_json(result.response.text)
        plan = plan.tidy().model_copy(update={"plan_type": "regular"})
        # treated/untreated drives the progress comparison, so it's decided by code, not the
        # model: an item is "treated" only if it's actually in his word bank.
        practiced = {_norm(w) for w in (memory_raw.get("word_bank") or {})}
        plan = plan.model_copy(update={"probe": [
            p.model_copy(update={"kind": "treated" if _norm(p.target) in practiced else "untreated"})
            for p in plan.probe
        ]})
        if len(plan.probe) < MIN_PROBE_ITEMS:
            # Without check-in items there's no progress measurement: don't accept it.
            raise ValueError(f"plan has {len(plan.probe)} probe items (need {MIN_PROBE_ITEMS}+)")
        # Games: keep only homework for games he actually has (no invented ids), with their
        # Hebrew names from the catalog; recommendations are saved separately (de-duplicated).
        known = {g.id: g for g in (games.games if games and not games.error else [])}
        plan = plan.model_copy(update={
            "game_homework": [h.model_copy(update={"name_he": known[h.game_id].name_he or h.game_id})
                              for h in plan.game_homework if h.game_id in known and known[h.game_id].route],
        })
        for rec in plan.games_app_feedback:
            store.add_games_recommendation(pid, sid, rec.model_dump(mode="json"))
        plan = plan.model_copy(update={"games_app_feedback": []})
        store.save_next_plan(pid, sid, {**plan.model_dump(mode="json"),
                                        "prompt_version": str(load_prompt().get("prompt_version"))})
        store.update_session(pid, sid, {"plan_status": PLAN_DONE, "plan_model": result.model, "plan_error": None})
        _log(f"{sid}: plan built ({plan.primary_goal.type.value}, {len(plan.probe)} probe, "
             f"{len(plan.practice)} practice; model {result.model})")
        return PLAN_DONE
    except Exception as exc:  # noqa: BLE001 -- recorded, retried by the sweep
        _log(f"{sid}: FAILED {type(exc).__name__}: {exc!s:.300}")
        try:
            store.update_session(pid, sid, {"plan_status": PLAN_FAILED,
                                            "plan_error": f"{type(exc).__name__}: {exc!s:.300}"})
        except Exception:  # noqa: BLE001
            pass
        return PLAN_FAILED
