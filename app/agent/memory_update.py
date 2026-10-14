"""Post-session memory update (SUMMARY_MODEL call #2): transcript -> updated memory.

  claim (transaction) -> build context -> tool phase (agent writes to a draft) ->
  consolidation phase (structured output: memory_prompt) -> save history + memory +
  session fields + flags -> memory_status done | skipped | failed

Never raises: a failure is recorded on the session (memory_status=failed) and retried later.
"""

import datetime as dt
import sys
from functools import lru_cache

import yaml
from google.genai import types

from app import check_in_set, sequencing
from app.steps import SequencingStep
from app.agent.memory_tools import MemoryDraft, build_memory_tools
from app.agent.runner import run_tool_loop
from app.class_plan import render_plan_full
from app.config import REPO_ROOT, Settings
from app.llm import generate
from app.schemas import SECTION_NAMES, ClassPlan, ConsolidatedMemory, MemoryDoc, MemorySections
from app.store import MEM_DONE, MEM_FAILED, MEM_SKIPPED, PLAN_PENDING, SessionStore

PROMPT_PATH = REPO_ROOT / "prompts" / "memory_update.yaml"
MIN_PATIENT_LINES = 2
RECENT_SUMMARIES = 5


def _log(message: str) -> None:
    print(f"[memory] {message}", file=sys.stderr, flush=True)


@lru_cache
def load_prompts() -> dict:
    return yaml.safe_load(PROMPT_PATH.read_text(encoding="utf-8"))


def _models(settings: Settings) -> list[str]:
    fallbacks = [m.strip() for m in settings.summary_fallback_models.split(",") if m.strip()]
    return [settings.summary_model, *fallbacks]


def format_transcript(turns: list[dict]) -> str:
    lines = []
    for t in turns:
        stamp = f"[{t.get('t_start_s', 0):6.1f}s]"
        if t["speaker"] == "tutor":
            cut = " (interrupted by him)" if t.get("interrupted") else ""
            lines.append(f"{stamp} TUTOR: {t.get('text', '')}{cut}")
        else:
            gem, live = (t.get("text") or "").strip(), (t.get("live_text") or "").strip()
            line = f"{stamp} HIM: {gem or '(no Gemini transcript)'}"
            if live and live != gem:
                line += f"\n{'':9} browser caption: {live}"
            lines.append(line)
    return "\n".join(lines)


def format_memory(memory: MemoryDoc) -> str:
    out = []
    for name in SECTION_NAMES:
        items = getattr(memory.sections, name)
        out.append(f"{name}:" + ("".join(f"\n  - {i}" for i in items) if items else " (empty)"))
    if memory.word_bank:
        words = ", ".join(f"{w} ({s.last_result.value if s.last_result else '?'})"
                          for w, s in list(memory.word_bank.items())[-30:])
        out.append(f"recent word-bank names (last result): {words}")
    return "\n".join(out)


def _recent_summaries_text(recent: list[dict]) -> str:
    if not recent:
        return "(no previous sessions)"
    return "\n".join(f"- {r.get('date')}: mood {r.get('mood')}; {r.get('summary')}" for r in recent)


def sequencing_result(plan, reported: dict | None) -> dict | None:
    """The session's sequencing result (14): the task, and the score computed by code from the
    order the agent heard -- or skipped / not reported."""
    step = next((s for s in (plan.steps if plan else []) if isinstance(s, SequencingStep)), None)
    if step is None:
        return None
    base = {"task": step.task, "title": step.title, "events": len(step.events)}
    if not reported:
        return {**base, "status": "not_reported"}
    if reported.get("skipped"):
        return {**base, "status": "skipped", "note": reported.get("note", "")}
    return {**base, "status": "done", **sequencing.score(reported["told_order"], len(step.events)),
            "told_order": reported["told_order"], "needed_help": reported["needed_help"],
            "low_confidence": reported["low_confidence"], "note": reported.get("note", "")}


def run_memory_update(
    store: SessionStore,
    client,
    settings: Settings,
    pid: str,
    sid: str,
    *,
    profile_text: str = "",
    today: dt.date | None = None,
    generate_fn=generate,
) -> str:
    """Returns the final memory_status. Assumes nothing; claims the session itself."""
    if not store.claim_for_memory(pid, sid):
        return "not_claimed"  # someone else is on it, or it's already done
    today = today or dt.date.today()
    try:
        turns = store.list_turns(pid, sid)
        patient_lines = [t for t in turns if t["speaker"] == "patient" and (t.get("text") or t.get("live_text"))]
        if len(patient_lines) < MIN_PATIENT_LINES:
            store.update_session(pid, sid, {"memory_status": MEM_SKIPPED})
            _log(f"{sid}: skipped ({len(patient_lines)} patient line(s))")
            return MEM_SKIPPED

        previous_raw = store.get_memory(pid)
        previous = MemoryDoc(**previous_raw) if previous_raw else MemoryDoc()
        recent = list((previous_raw or {}).get("recent_summaries", []))
        draft = MemoryDraft(
            sections=MemorySections(**previous.sections.model_dump()),
            word_bank={w: s.model_copy() for w, s in previous.word_bank.items()},
            today=today,
        )
        prompts = load_prompts()
        models = _models(settings)
        # The plan this session used (05): lets the agent score its check-in items.
        plan = None
        session = store.get_session(pid, sid) or {}
        raw_plan = session.get("class_plan")
        if raw_plan:
            try:
                plan = ClassPlan(**raw_plan)
                draft.probe_kinds = {p.target: p.kind for p in plan.probe}
            except Exception:  # noqa: BLE001 -- an old/odd plan must not break the update
                plan = None
        plan_text = render_plan_full(plan) if plan else "(no plan: a free session)"
        # Steps mode (13): what she reported finished, in order -- a record next to the transcript.
        steps_done = session.get("steps_done") or []
        if steps_done:
            plan_text += "\n\nSteps she reported finished (next_step):\n" + "\n".join(
                f"- [{st.get('at_s', 0):.0f}s] {st.get('done', '')}: {st.get('how_it_went', '')}" for st in steps_done)

        # ---- phase 1: tools ---------------------------------------------------------
        context = (
            f"# PATIENT PROFILE\n{profile_text or '(none)'}\n\n"
            f"# CURRENT MEMORY\n{format_memory(previous)}\n\n"
            f"# RECENT SESSION SUMMARIES (oldest first)\n{_recent_summaries_text(recent)}\n\n"
            f"# TODAY'S PLAN (what the tutor was asked to do)\n{plan_text}\n\n"
            f"# TRANSCRIPT OF THE SESSION THAT JUST ENDED ({today.isoformat()})\n{format_transcript(turns)}"
        )
        run = run_tool_loop(
            client, models, prompts["tool_phase"], context, build_memory_tools(draft),
            max_rounds=settings.memory_max_tool_rounds, generate_fn=generate_fn,
        )

        # The sequencing task must be reported (13.10: the agent skipped it, so no score): one
        # short extra round with only that tool when the plan had one and it's missing.
        if plan and any(isinstance(s, SequencingStep) for s in plan.steps) and draft.sequencing is None:
            seq_tool = [t for t in build_memory_tools(draft) if t.name == "record_sequencing"]
            run_tool_loop(client, models, prompts["tool_phase"] + "\n\nYOU MISSED ONE: TODAY'S PLAN had a "
                          "sequencing task and you didn't record it. Call record_sequencing now (skipped=true if "
                          "she didn't run it).", context, seq_tool, max_rounds=2, generate_fn=generate_fn)

        # ---- phase 2: consolidation -------------------------------------------------
        summary_text = draft.summary.summary if draft.summary else "(no summary saved)"
        updated = MemoryDoc(sections=draft.sections, word_bank=draft.word_bank)
        consolidation_input = (
            f"# MEMORY SECTIONS\n{format_memory(updated)}\n\n"
            f"# LAST SESSION ({today.isoformat()})\n{summary_text}\n\n"
            f"# EARLIER SESSIONS\n{_recent_summaries_text(recent)}\n\n"
            f"# PREVIOUS MEMORY TEXT (for continuity)\n{previous.memory_prompt or '(none)'}"
        )
        result = generate_fn(
            client, models, consolidation_input,
            types.GenerateContentConfig(
                system_instruction=prompts["consolidation"],
                response_mime_type="application/json",
                response_schema=ConsolidatedMemory,
                temperature=0.3,
            ),
        )
        consolidated = result.response.parsed
        if not isinstance(consolidated, ConsolidatedMemory):
            consolidated = ConsolidatedMemory.model_validate_json(result.response.text)

        # ---- save -------------------------------------------------------------------
        if draft.summary:
            recent.append({"date": today.isoformat(), "session_id": sid,
                           "mood": draft.summary.mood.value, "summary": draft.summary.summary})
        new_memory = MemoryDoc(
            memory_prompt=consolidated.memory_prompt.strip(),
            sections=draft.sections,
            word_bank=draft.word_bank,
            focus_next_session=consolidated.focus_next_session[:4],
            last_session_id=sid,
            sessions_processed=previous.sessions_processed + 1,
            prompt_version=str(prompts.get("prompt_version")),
        ).model_dump(mode="json")
        new_memory["recent_summaries"] = recent[-RECENT_SUMMARIES:]
        store.save_memory(pid, sid, new_memory, previous_raw)
        for flag in draft.flags:
            store.add_flag(pid, sid, flag.model_dump(mode="json"))
        session_fields = {
            "memory_status": MEM_DONE,
            "plan_status": PLAN_PENDING,  # next: build the next session's plan (05)
            "probe_results": draft.probe_results,
            "own_names": draft.own_names,  # names he found / couldn't find in free talk (12)
            "names_game": draft.names_game,
            "sequencing": sequencing_result(plan, draft.sequencing),  # telling things in order (14)
            "memory_error": None,
            "memory_model": result.model,
            "memory_attempts": run.attempts + result.attempts,
            "memory_tool_calls": len(run.calls),
            "memory_tool_errors": sum(not c.ok for c in run.calls),
        }
        if draft.summary:
            session_fields.update(draft.summary.model_dump(mode="json"))
        store.update_session(pid, sid, session_fields)
        # The names game's answers also go to the stable set (12): its rotation and history.
        current_set = store.get_check_in_set(pid)
        if current_set and check_in_set.record_results(current_set, draft.probe_results, sid, today):
            store.save_check_in_set(pid, current_set)
        _log(f"{sid}: done ({len(run.calls)} tool calls, {len(draft.flags)} flag(s), model {result.model})")
        return MEM_DONE
    except Exception as exc:  # noqa: BLE001 -- recorded, retried on a later /start
        _log(f"{sid}: FAILED {type(exc).__name__}: {exc!s:.300}")
        try:
            store.update_session(pid, sid, {"memory_status": MEM_FAILED,
                                            "memory_error": f"{type(exc).__name__}: {exc!s:.300}"})
        except Exception:  # noqa: BLE001
            pass
        return MEM_FAILED
