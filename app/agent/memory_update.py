"""Post-session memory update (SUMMARY_MODEL call #2): transcript -> updated memory.

  claim (transaction) -> build context -> tool phase (agent writes to a draft) ->
  the memory text rendered by code from the sections (16) -> save history + memory +
  session fields + flags -> memory_status done | skipped | failed

Never raises: a failure is recorded on the session (memory_status=failed) and retried later.
"""

import datetime as dt
import sys
from functools import lru_cache

import yaml

from app import telemetry
from app import check_in_set, missing_areas, probes, sequencing, summarizing
from app.steps import AreaProbeStep, SequencingStep, StoryProbeStep, SummaryStep, ViewStep
from app.agent.memory_tools import Inferring, MemoryDraft, add_vocabulary, build_memory_tools
from app.patient_profile import (AREA_NAMES, MAX_HISTORY, MAX_POINTS, account_profile, needs_lines,
                                 render_inferred)
from app.agent.runner import run_tool_loop
from app.memory_text import render_memory
from app.class_plan import render_plan_full
from app.config import REPO_ROOT, Settings
from app.llm import generate
from app.schemas import SECTION_NAMES, ClassPlan, MemoryDoc, MemorySections
from app.store import MEM_DONE, MEM_FAILED, MEM_SKIPPED, PLAN_PENDING, SessionStore
from app.transcripts import strip_markers

PROMPT_PATH = REPO_ROOT / "prompts" / "memory_update.yaml"
MIN_PATIENT_LINES = 2
RECENT_SUMMARIES = 5


def _log(message: str) -> None:
    print(f"[memory] {message}", file=sys.stderr, flush=True)
    telemetry.note(f"[memory] {message}")  # also in the running agent's log (19)


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
            lines.append(f"{stamp} TUTOR: {strip_markers(t.get('text', ''))}{cut}")
        else:
            # no transcription markers (20): sessions saved before the page dropped them
            gem, live = strip_markers(t.get("text") or ""), strip_markers(t.get("live_text") or "")
            line = f"{stamp} HIM: {gem or '(no Gemini transcript)'}"
            if live and live != gem:
                line += f"\n{'':9} browser caption: {live}"
            if t.get("matched_target"):  # the page heard the expected name in one of his transcripts (20)
                line += f"\n{'':9} (the page matched the names-game name: {t['matched_target']})"
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


def needs_history_text(areas: dict) -> str:
    """Per area: the current level and the levels over his sessions -- for the agent's context."""
    out = []
    for line, (area, a) in zip(needs_lines({"areas": areas}), ((k, areas[k]) for k in AREA_NAMES if k in areas)):
        levels = [h.get("level", "") for h in a.get("history") or []]
        out.append(line + (f" | history: {', '.join(levels[-8:])}" if levels else ""))
    return "\n".join(out)


def save_inferred(store, pid: str, sid: str, draft: MemoryDraft, today: dt.date) -> None:
    """The needs profile and the inferred profile (15.5), after the session. His own names (12) go
    into the vocabulary by code. Never over an uploaded profile (re-read: the family may have just
    uploaded one)."""
    inf = draft.inferring
    for area in inf.changed:  # a level per session that showed the area: his progress
        a = inf.areas[area]
        entry = {"date": today.isoformat(), "session": sid, "level": a.get("app_level") or a.get("level")}
        history = [h for h in (a.get("history") or []) if h.get("session") != sid] + [entry]
        inf.areas[area] = {**a, "session": sid, "date": today.isoformat(), "history": history[-MAX_HISTORY:]}
    for point in inf.new_points:
        point.update(id=f"{sid}-{len(inf.points)}", date=today.isoformat(), session=sid)
        inf.points.append(point)
    needs = {"areas": inf.areas, "therapist_points": inf.points[-MAX_POINTS:]}
    if inf.changed or inf.new_points:  # merged: the doc also keeps other things (e.g. pending checks, 17)
        store.save_needs(pid, {**(store.get_needs(pid) or {}), **needs})
    if not inf.profile or account_profile(store, pid).source == "uploaded":
        return  # an uploaded profile is never touched
    for own in draft.own_names:
        add_vocabulary(inf, own.get("word", ""))
    text = render_inferred(inf.about, inf.vocabulary, needs)
    if text:
        store.save_profile(pid, text, "inferred", "app", extra={"about": inf.about, "vocabulary": inf.vocabulary,
                                                                "vocabulary_blocked": inf.blocked})


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


def _area_probe_result(plan, reported: dict | None) -> dict | None:
    step = next((s for s in (plan.steps if plan else []) if isinstance(s, AreaProbeStep)), None)
    if step is None:
        return None
    return missing_areas.score(step.area, [{"text": t} for t in step.items], reported)


def summarizing_result(plan, reported: dict | None) -> dict | None:
    """The session's summary result (17): the title and size, and the score computed by code from the
    main ideas the agent heard -- or skipped / not reported."""
    step = next((s for s in (plan.steps if plan else []) if isinstance(s, SummaryStep)), None)
    if step is None:
        return None
    base = {"title": step.title, "ideas": len(step.main_ideas)}
    if not reported:
        return {**base, "status": "not_reported"}
    if reported.get("skipped"):
        return {**base, "status": "skipped", "note": reported.get("note", "")}
    return {**base, "status": "done", **summarizing.score(reported["conveyed"], len(step.main_ideas)),
            "conveyed": reported["conveyed"], "needed_help": reported["needed_help"],
            "low_confidence": reported["low_confidence"], "note": reported.get("note", "")}


@telemetry.job("memory_update")
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
        # His needs, after every session (15.5): for every account -- with an uploaded profile for the
        # family's eyes only (status, progress, points for his therapist); without one, the agent also
        # keeps the inferred profile.
        prof = store.get_profile(pid) or {}
        needs_doc = store.get_needs(pid) or {}
        draft.inferring = Inferring(about=list(prof.get("about") or []), vocabulary=list(prof.get("vocabulary") or []),
                                    blocked=list(prof.get("vocabulary_blocked") or []),
                                    areas=dict(needs_doc.get("areas") or {}),
                                    points=list(needs_doc.get("therapist_points") or []),
                                    profile=account_profile(store, pid).source != "uploaded")
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
            + f"# HIS NEEDS SO FAR (record_needs updates them; history oldest -> newest)\n"
            f"{needs_history_text(draft.inferring.areas) or '(none yet)'}\n\n"
            f"# POINTS FOR HIS THERAPIST ALREADY ON THE LIST\n"
            f"{chr(10).join('- ' + p['text'] for p in draft.inferring.points) or '(none)'}\n\n" +
            f"# TRANSCRIPT OF THE SESSION THAT JUST ENDED ({today.isoformat()})\n{format_transcript(turns)}"
        )
        run = run_tool_loop(
            client, models, prompts["tool_phase"], context, build_memory_tools(draft),
            max_rounds=settings.memory_max_tool_rounds, generate_fn=generate_fn,
        )

        # The sequencing task must be reported (13.10: the agent skipped it, so no score): one
        # short extra round with only that tool when the plan had one and it's missing.
        for cls, field_, tool_name, what in ((SequencingStep, "sequencing", "record_sequencing", "a sequencing task"),
                                             (SummaryStep, "summarizing", "record_summary", "a summary task"),
                                             (StoryProbeStep, "story_probe", "record_story_probe", "a story to retell"),
                                             (AreaProbeStep, "area_probe", "record_area_probe", "a short measuring game")):
            if plan and any(isinstance(s, cls) for s in plan.steps) and getattr(draft, field_) is None:
                missed = [t for t in build_memory_tools(draft) if t.name == tool_name]
                run_tool_loop(client, models, prompts["tool_phase"] + f"\n\nYOU MISSED ONE: TODAY'S PLAN had {what} "
                              f"and you didn't record it. Call {tool_name} now (skipped=true if she didn't run it).",
                              context, missed, max_rounds=2, generate_fn=generate_fn)

        # ---- save -------------------------------------------------------------------
        if draft.summary:
            recent.append({"date": today.isoformat(), "session_id": sid,
                           "mood": draft.summary.mood.value, "summary": draft.summary.summary})
        new_memory = MemoryDoc(
            sections=draft.sections,
            word_bank=draft.word_bank,
            focus_next_session=(draft.focus if draft.focus is not None else previous.focus_next_session)[:4],
            last_session_id=sid,
            sessions_processed=previous.sessions_processed + 1,
            prompt_version=str(prompts.get("prompt_version")),
        ).model_dump(mode="json")
        new_memory["recent_summaries"] = recent[-RECENT_SUMMARIES:]
        # The text she reads, assembled by code from the checked sections (16): nothing dropped,
        # nothing added -- no model rewrite.
        new_memory["memory_prompt"] = render_memory(new_memory)
        store.save_memory(pid, sid, new_memory, previous_raw)
        if draft.inferring is not None:
            save_inferred(store, pid, sid, draft, today)
        for flag in draft.flags:
            store.add_flag(pid, sid, flag.model_dump(mode="json"))
        session_fields = {
            "memory_status": MEM_DONE,
            "plan_status": PLAN_PENDING,  # next: build the next session's plan (05)
            "probe_results": draft.probe_results,
            "own_names": draft.own_names,  # names he found / couldn't find in free talk (12)
            "names_game": draft.names_game,
            "sequencing": sequencing_result(plan, draft.sequencing),  # telling things in order (14)
            "summarizing": summarizing_result(plan, draft.summarizing),  # a short text in his own words (17)
            # measuring like a therapist (17): the story probe, his own view, how he talked (by code)
            "story_probe": probes.story_result(next((s for s in (plan.steps if plan else [])
                                                     if isinstance(s, StoryProbeStep)), None), draft.story_probe),
            "his_view": ({**draft.his_view, "status": "done"} if draft.his_view else
                         ({"status": "not_reported"} if plan and any(isinstance(s, ViewStep) for s in plan.steps)
                          else None)),
            "talk": probes.talk_measures(turns),
            "area_probe": _area_probe_result(plan, draft.area_probe),  # 17.5: a missing area's measurement
            "memory_error": None,
            "memory_model": run.models[-1] if run.models else None,
            "memory_attempts": run.attempts,
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
        _log(f"{sid}: done ({len(run.calls)} tool calls, {len(draft.flags)} flag(s), model {run.models[-1] if run.models else None})")
        return MEM_DONE
    except Exception as exc:  # noqa: BLE001 -- recorded, retried on a later /start
        _log(f"{sid}: FAILED {type(exc).__name__}: {exc!s:.300}")
        try:
            store.update_session(pid, sid, {"memory_status": MEM_FAILED,
                                            "memory_error": f"{type(exc).__name__}: {exc!s:.300}"})
        except Exception:  # noqa: BLE001
            pass
        return MEM_FAILED
