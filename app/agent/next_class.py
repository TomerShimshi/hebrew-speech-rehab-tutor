"""Next-class builder (SUMMARY_MODEL call #3): updated memory -> the next session's ClassPlan.

Phases:
  0. a new names-game set when one is due (12): one structured call, checked by code.
  1. optional research (07): a short tool loop with one tool, research_technique(question),
     offered only when research is possible (Tavily key, daily/monthly budget). At most one
     research run per plan; any failure here is ignored -- research is an extra.
  2. the plan, built STEP BY STEP with tools (13.5, app/agent/plan_tools.py): each step checked
     when it's added, in the builder's order, to a time budget at his pace.
Runs right after a successful memory update (and from the hourly sweep). Never raises:
failures are recorded as plan_status.
"""

import datetime as dt
import re
import sys
from functools import lru_cache

import yaml
from google.genai import types

from app import telemetry
from app import check_in_set, missing_areas, probes, progress, sequencing, summarizing, word_bank
from app.agent.memory_update import format_memory
from app.agent.research import personal_terms, research_technique, search_available
from app.steps import MISSING_AREA_STEPS, AreaProbeStep, StoryProbeStep, ViewStep
from app.agent.plan_tools import BUDGET_MINUTES, MIN_ACCEPT, PlanDraft, build_plan_tools
from app.agent.runner import Tool, run_tool_loop
from app.class_plan import add_one_check, fixed_plan, missed_checks, with_checks
from app.patient_profile import account_profile, needs_lines
from app.config import REPO_ROOT, Settings
from app.games import render_games_for_plan
from app.llm import generate
from app.schemas import CheckInItem, CheckInProposal, MemoryDoc
from app.store import ENDED, PLAN_DONE, PLAN_FAILED, SessionStore

PROMPT_PATH = REPO_ROOT / "prompts" / "next_class.yaml"
TECHNIQUES_PATH = REPO_ROOT / "prompts" / "therapy_techniques.yaml"
MIN_SET_ITEMS = 4  # a names-game set needs at least this many usable names
PLAN_MAX_ROUNDS = 16  # the plan builder's tool loop (13.5)

# The research phase's one tool (07); a constant so the tools catalog (docs/tools.md) lists it.
RESEARCH_TOOL = dict(
    name="research_technique",
    description=("Look up evidence-based home-practice techniques (professional sources) for ONE "
                 "generic clinical question in English. Never include names, places or Hebrew."),
    parameters={"type": "object", "properties": {"question": {"type": "string", "description":
                "e.g. 'mild anomia for proper names in a fluent speaker; retrieval practice at home'"}},
                "required": ["question"]},
)
PACE_SESSIONS = 5  # his pace (12b) from this many recent real sessions
FAST_PACE, SLOW_PACE = 3.2, 2.0  # his answers per minute: a fast talker uses a plan up sooner
GROUNDING_SESSIONS = 3  # his own lines in this many recent transcripts count as "his data"
# The question addresses HIM personally ("your friend", "with you"...): then the answer is about
# his own life and must be grounded, whatever the model's about_his_life says.
PERSONAL = re.compile(r"(שלך|שלכם|איתך|אליך|אצלך|אותך|בשבילך|אשתך|בעלך|בנך|בתך|ילדיך|נכדיך|נכדך|"
                      r"חברך|חבריך|אחיך|אחותך|הוריך|אביך|אמך)")
NIQQUD = re.compile(r"[\u0591-\u05C7]")
# Answers he gets right anyway: as NEW (untreated) check-in items they can't show progress.
TOO_FAMOUS = {"ירושלים", "תל אביב", "תל אביב יפו", "תל-אביב", "חיפה", "אילת", "באר שבע", "ים המלח",
              "הכנרת", "כנרת", "הכותל", "הכותל המערבי", "ישראל"}


def _log(message: str) -> None:
    print(f"[next_class] {message}", file=sys.stderr, flush=True)
    telemetry.note(f"[next_class] {message}")  # also in the running agent's log (19)


@lru_cache
def load_prompt() -> dict:
    return yaml.safe_load(PROMPT_PATH.read_text(encoding="utf-8"))


@lru_cache
def techniques_text() -> str:
    return TECHNIQUES_PATH.read_text(encoding="utf-8")


def _norm(word: str) -> str:
    return " ".join(word.split()).strip()


def _plain(text: str) -> str:
    """For matching names: no vowel marks, no punctuation, single spaces."""
    text = NIQQUD.sub("", text or "")
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def grounding_text(store: SessionStore, pid: str, memory_raw: dict, profile_text: str, notes: str) -> str:
    """Everything that is really known about his life: memory, profile, planner notes, and his
    OWN lines in the last few transcripts (a name he said himself counts). NOT the word bank: a
    word there only means the tutor practiced it -- and that may itself have been invented."""
    parts = [profile_text, notes, memory_raw.get("memory_prompt", ""), *memory_raw.get("focus_next_session", [])]
    for items in (memory_raw.get("sections") or {}).values():
        parts += [str(i) for i in items or []]
    for session in store.list_sessions(pid, GROUNDING_SESSIONS):
        for turn in store.list_turns(pid, session["id"]):
            if turn.get("speaker") == "patient":
                parts += [turn.get("text", ""), turn.get("live_text", "")]
    return f" {_plain(' '.join(p for p in parts if p))} "


def _about_his_life(item) -> bool:
    asked = getattr(item, "elicit", None) or getattr(item, "question", "")
    return bool(getattr(item, "about_his_life", False) or PERSONAL.search(f"{asked} {getattr(item, 'bridge', '')}"))


def _grounded(target: str, known: str) -> bool:
    # Hebrew attaches prefixes to words: "ברמת גן", "והירקון", "מחיפה" all count for the name.
    name = _plain(target)
    return bool(name) and re.search(rf"(?<!\w)[בהולמשכ]{{0,2}}{re.escape(name)}(?!\w)", known) is not None


def practice_checker(known: str, untreated: set[str]):
    """Why a practice step is rejected, said back to the builder at once (13.5): a name about his
    life must be in his data (8.5); an untreated names-game name is never practiced (12)."""
    def check(step) -> str | None:
        if _about_his_life(step) and not _grounded(step.name, known):
            return (f"rejected: {step.name} is not in his data (memory, profile, notes, his own words) -- never "
                    f"invent his life. Use a name from his data, or a less-famous general place.")
        if _norm(step.name) in untreated:
            return f"rejected: {step.name} is an untreated names-game name -- those are never practiced."
        return None
    return check


def enforce_set_rules(proposal: CheckInProposal, bank: dict, known: str) -> list[CheckInItem]:
    """The names-game set, checked by code (12): treated = PRACTICED in the word bank (not just
    there); names about his life must be in his data; no too-famous new names; no repeats."""
    items, seen = [], set()
    for item in proposal.items:
        name = _norm(item.target)
        if not name or name in seen or not item.question.strip():
            continue
        if _about_his_life(item) and not _grounded(item.target, known):
            _log(f"set: dropped {item.target!r} (about his life, not in his data)")
            continue
        treated = word_bank.is_treated(bank.get(name))
        if not treated and name in TOO_FAMOUS:
            _log(f"set: dropped too-famous new name {item.target!r}")
            continue
        seen.add(name)
        items.append(item.model_copy(update={"target": name, "kind": "treated" if treated else "untreated"}))
    if len(items) < MIN_SET_ITEMS:
        raise ValueError(f"names-game set has {len(items)} usable names (need {MIN_SET_ITEMS}+)")
    return items[:10]


def speaking_pace(store: SessionStore, pid: str) -> list[dict]:
    """His pace in his last real sessions (12b): minutes, his answers per minute, words per
    answer. A fast talker gets through a plan sooner -- then the plan must be bigger."""
    rows = []
    for s in store.list_sessions(pid, 12):
        start, end = s.get("started_at"), s.get("ended_at")
        if s.get("status") != ENDED or (s.get("turn_count") or 0) < 6 or not start or not end:
            continue
        minutes = (end - start).total_seconds() / 60
        if minutes < 2:
            continue
        his = [(t.get("text") or t.get("live_text") or "") for t in store.list_turns(pid, s["id"])
               if t.get("speaker") == "patient"]
        his = [h for h in his if h.strip()]
        if not his:
            continue
        rows.append({"date": start.date().isoformat(), "minutes": round(minutes, 1),
                     "answers_per_min": round(len(his) / minutes, 1),
                     "words_per_answer": round(sum(len(h.split()) for h in his) / len(his), 1)})
        if len(rows) == PACE_SESSIONS:
            break
    return rows


STEP_SESSIONS = 10  # his step lengths from this many recent sessions with step reports
MIN_SAMPLES = 2  # a kind's measured length is used once it has this many samples


def step_minutes(store: SessionStore, pid: str) -> dict[str, float]:
    """How long each step kind really takes HIM (13.5): from his recent sessions' steps and her
    next_step reports (seconds since the start). The median per kind; kinds without enough data
    are left out (the class default applies)."""
    from app.steps import STEP_CLASSES
    samples: dict[str, list[float]] = {}
    for s in store.list_sessions(pid, STEP_SESSIONS):
        # Only sessions on the current way of talking (prompt 3.x): before it she moved on after one
        # answer, and those lengths would plan a rushed session (12.10).
        if not str(s.get("prompt_version") or "").startswith("3."):
            continue
        agenda, done = s.get("agenda") or [], s.get("steps_done") or []
        prev = 0.0
        for step, report in zip(agenda, done):
            at = float(report.get("at_s") or 0)
            if at > prev:
                samples.setdefault(step.get("kind"), []).append((at - prev) / 60)
            prev = max(prev, at)
    out = {}
    for kind, values in samples.items():
        cls = STEP_CLASSES.get(kind)
        if cls is None or len(values) < MIN_SAMPLES:  # an old kind, or too little data
            continue
        values = sorted(values)
        # a talking step shorter than its floor means she rushed: plan for a real conversation
        out[kind] = round(max(values[len(values) // 2], cls.MIN_MINUTES), 2)
    return out


def sequencing_history(store: SessionStore, pid: str) -> tuple[list[dict], str]:
    """His recent sequencing results (14), newest first, and the next plan's task. Every regular
    session has one (Tomer, 13.10: more practice, and a fuller progress chart); the two kinds take
    turns -- the other one than his last task, so each is measured the same way every other time."""
    results, last_task = [], None
    for s in store.list_sessions(pid, 12):
        if s.get("status") != ENDED or (s.get("class_plan") or {}).get("plan_type") != "regular":
            continue
        seq = s.get("sequencing") or {}
        if last_task is None and seq.get("task"):
            last_task = seq["task"]
        if seq.get("status") == "done":
            results.append(seq)
    return results[:5], "retell" if last_task == "scrambled" else "scrambled"


def apply_missing_areas(store: SessionStore, pid: str, today: dt.date) -> None:
    """Confirming first (17.5): each missing area's status from the needs' history; a re-check item
    queued while it's open (not for an uploaded profile: no new checks in his sessions, 17); a confirmed
    area handed to the progress rules at level 1, less time, with a notice to the family."""
    needs = store.get_needs(pid) or {}
    areas = dict(needs.get("areas") or {})
    pending = list(needs.get("pending_checks") or [])
    uploaded = account_profile(store, pid).source == "uploaded"
    prog = store.get_progress(pid) or {}
    points = list(needs.get("therapist_points") or [])
    changed = False
    for area in missing_areas.AREAS:
        st = missing_areas.status(areas.get(area))
        if areas.get(area) and areas[area].get("status") != st:
            areas[area] = {**areas[area], "status": st}
            changed = True
        if st in ("seen_once", "rechecking") and not uploaded and all(p.get("area") != area for p in pending):
            pending.append(missing_areas.recheck_step(area, len(areas.get(area, {}).get("history") or [])))
            changed = True
        if st == "confirmed" and not ((prog.get("areas") or {}).get(area) or {}).get("active"):
            prog = missing_areas.hand_over(prog, area, today.isoformat())
            store.save_progress(pid, prog)
            text = f"האפליקציה מצאה קושי ב{progress.AREA_HE[area]} ב־2 מתוך 3 שיחות, ומתחילה לתרגל אותו בהדרגה"
            if all(p.get("text") != text for p in points):
                points.append({"id": f"confirmed-{today.isoformat()}-{area}", "text": text, "why": "confirmed (17.5)",
                               "evidence": [], "status": "new", "date": today.isoformat(), "session": None})
            _log(f"missing areas: {area} confirmed -> practice starts small")
            changed = True
    if changed:
        store.save_needs(pid, {**needs, "areas": areas, "pending_checks": pending, "therapist_points": points[-60:]})


def apply_progress(store: SessionStore, pid: str, today: dt.date) -> tuple[str, str]:
    """Runs the progress rules (17) on his results, saves the settings and the log, turns new
    decisions into points for his therapist. Returns HIS PROGRESS and the naming share."""
    sessions = store.list_sessions(pid, 40)
    doc, decisions = progress.update(store.get_progress(pid), sessions, today)
    store.save_progress(pid, {**(store.get_progress(pid) or {}), **doc})
    if decisions:
        needs = store.get_needs(pid) or {}
        points = list(needs.get("therapist_points") or [])
        for d in decisions:
            _log(f"progress: {d['area']} {d['rule']} -- {d['reason']}")
            if all(p.get("text") != d["point"] for p in points):
                points.append({"id": f"progress-{today.isoformat()}-{d['area']}", "text": d["point"],
                               "why": f"{d['rule']}: {d['reason']}", "evidence": [], "status": "new",
                               "date": today.isoformat(), "session": None})
        store.save_needs(pid, {**needs, "therapist_points": points[-60:]})
    naming = (doc.get("areas") or {}).get("naming") or {}
    return progress.render(doc, progress.series(sessions)), naming.get("share", "normal")


def discourse_turn(store: SessionStore, pid: str) -> str:
    """Which discourse task the next plan has (17): the sequencing task and the summary take turns,
    session by session -- the other one than his last regular session that had either."""
    for s in store.list_sessions(pid, 12):
        if s.get("status") != ENDED or (s.get("class_plan") or {}).get("plan_type") != "regular":
            continue
        if s.get("sequencing"):
            return "summary"
        if s.get("summarizing"):
            return "sequencing"
    return "sequencing"


def summarizing_history(store: SessionStore, pid: str) -> list[dict]:
    """His recent summary results (17), newest first (done only)."""
    out = []
    for s in store.list_sessions(pid, 12):
        r = s.get("summarizing") or {}
        if s.get("status") == ENDED and r.get("status") == "done":
            out.append(r)
    return out[:5]


def render_summarizing(results: list[dict], recommended: int) -> str:
    lines = [f"- {r.get('title')}: {r.get('ideas_conveyed')}/{r.get('ideas')} main ideas "
             f"({r.get('ideas_pct')}%){', with help' if r.get('needed_help') else ''}" for r in results]
    return "\n".join((lines or ["(no summaries yet)"]) + [f"Recommended size of the next summary: {recommended} main ideas."])


def render_sequencing(results: list[dict], recommended: int, task: str) -> str:
    lines = [f"- {r.get('task')}: {r.get('title')}, {r.get('events')} events -> {r.get('order_pct')}% in order, "
             f"{r.get('events_included')}/{r.get('events')} included{', with help' if r.get('needed_help') else ''}"
             for r in results] or ["(no sequencing tasks yet)"]
    lines.append(f"Recommended size of the next task: {recommended} events.")
    lines.append(f"Its kind when it's due: task={task} (the two kinds take turns).")
    return "\n".join(lines)


def pace_label(rows: list[dict]) -> str:
    if not rows:
        return "typical"
    rate = sum(r["answers_per_min"] for r in rows) / len(rows)
    return "FAST" if rate >= FAST_PACE else "SLOW" if rate <= SLOW_PACE else "typical"


def render_pace(rows: list[dict]) -> str:
    if not rows:
        return "(no sessions yet: plan for a typical pace)"
    rate = sum(r["answers_per_min"] for r in rows) / len(rows)
    label = pace_label(rows)
    lines = [f"- {r['date']}: {r['minutes']} min, {r['answers_per_min']} answers/min, "
             f"{r['words_per_answer']} words per answer" for r in rows]
    return "\n".join([*lines, f"Overall: {rate:.1f} answers per minute -> {label} pace."])


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


def _technique_lines(techniques: list[dict]) -> str:
    return "\n".join(f"  - {t.get('name')}: {t.get('how_to')} (e.g. \"{t.get('hebrew_example')}\")"
                     for t in techniques)


def render_notes(notes: list[dict]) -> str:
    """Recent research findings (newest first), for the builder. No URLs: it doesn't need them."""
    if not notes:
        return "(none yet)"
    return "\n".join(f"- Q: {n.get('question')}\n  {n.get('summary', '')}\n{_technique_lines(n.get('techniques', []))}"
                     for n in notes)


def research_available(store: SessionStore, settings: Settings, pid: str, now: dt.datetime) -> bool:
    return bool(store.research_runs_on(pid, now.date().isoformat()) < settings.research_daily_limit
                and search_available(store, settings, now.strftime("%Y-%m")))


def run_research_phase(store, client, settings, pid, context, personal, now, generate_fn, research_fn) -> dict | None:
    """Lets the builder ask ONE research question. Returns {question, status, ...}; status
    "not_needed" (with the builder's reason) when it chose not to, None if the phase failed."""
    outcome: dict = {}

    def handle(args: dict) -> dict:
        if outcome.get("status") not in (None, "rejected"):
            raise ValueError("research was already done for this plan; finish now")
        question = str(args.get("question", ""))
        result = research_fn(store, client, settings, pid, question, personal=personal, now=now,
                             generate_fn=generate_fn)
        outcome.clear()
        outcome.update({"question": question, **result})
        return result

    tool = Tool(**RESEARCH_TOOL, handler=handle)
    try:
        run = run_tool_loop(client, _models(settings), load_prompt()["research_phase"], context, [tool],
                            max_rounds=3, generate_fn=generate_fn)
    except Exception as exc:  # noqa: BLE001 -- research is optional
        _log(f"research phase failed (plan continues): {type(exc).__name__}: {exc!s:.200}")
        return outcome or None
    if not outcome:
        reason = " ".join(run.final_text.split())[:300]
        _log(f"no research: {reason}")
        return {"status": "not_needed", "reason": reason}
    return outcome


def render_check_in_set(current: dict | None) -> str:
    if not current or not current.get("items"):
        return "(none yet)"
    lines = [f"since {current.get('created_on')}, played in {current.get('sessions_played', 0)} session(s)"]
    for i in current["items"]:
        last = ", ".join(r.get("result", "?") for r in i.get("results", [])[-3:]) or "not asked yet"
        lines.append(f"- {i['target']} ({i.get('kind')}): {last}")
    return "\n".join(lines)


def build_context(memory_raw: dict, recent_plans: list[dict], profile_text: str, today: dt.date,
                  games_text: str = "(no games account linked)", notes_text: str = "(none yet)",
                  caregiver_notes: str = "", check_in: dict | None = None,
                  pace: list[dict] | None = None, sequencing_text: str = "(no sequencing tasks yet)",
                  needs_text: str = "", summarizing_text: str = "(no summaries yet)",
                  discourse: str = "sequencing", progress_text: str = "") -> str:
    memory = MemoryDoc(**memory_raw)
    due = word_bank.due_words(memory.word_bank, today)
    bank = ", ".join(
        f"{w} ({s.source.value}; last: {s.last_result.value if s.last_result else '?'}, next due {s.next_due})"
        for w, s in list(memory.word_bank.items())[-25:]
    ) or "(empty)"
    recent = "\n".join(f"- {r.get('date')}: mood {r.get('mood')}; {r.get('summary')}"
                       for r in memory_raw.get("recent_summaries", [])) or "(none)"
    return (
        f"# TODAY\n{today.isoformat()} ({today.strftime('%A')})\n\n"
        f"# PATIENT PROFILE\n{profile_text or '(none)'}\n\n"
        f"# NOTES FROM THE FAMILY / THERAPIST (follow them; they override the memory)\n"
        f"{caregiver_notes.strip() or '(none)'}\n\n"
        f"# MEMORY (what the tutor knows about him)\n{memory.memory_prompt}\n\n"
        f"# MEMORY SECTIONS\n{format_memory(memory)}\n\n"
        f"# FOCUS POINTS FROM THE LAST SESSION\n" + ("\n".join(f"- {f}" for f in memory.focus_next_session) or "(none)") + "\n\n"
        f"# WORD BANK\ndue for practice today (names he couldn't find on his own first): {', '.join(due) or '(none)'}\n"
        f"all recent (source: practiced / self_found / not_found / probe): {bank}\n\n"
        f"# NAMES GAME SET (the stable check-in set; untreated names must NEVER be practiced)\n"
        f"{render_check_in_set(check_in)}\n\n"
        f"# RECENT SESSIONS (oldest first)\n{recent}\n\n"
        f"# HIS PACE (newest first; size the plan to fill ~9 minutes at this pace)\n{render_pace(pace or [])}\n\n"
        f"# HIS DISCOURSE TASK (REQUIRED in every plan: the sequencing task and the summary take turns)\n"
        f"This time: {'a SUMMARY (add_summary)' if discourse == 'summary' else 'a SEQUENCING task (add_sequencing)'}.\n\n"
        f"# HIS SEQUENCING (telling things in order; newest first)\n{sequencing_text}\n\n"
        f"# HIS SUMMARIZING (telling a short text in his own words; newest first)\n{summarizing_text}\n\n"
        f"# HIS PROGRESS (measured by code; the app's settings per area -- follow them)\n"
        f"{progress_text or '(not enough results yet)'}\n\n"
        f"# HIS NEEDS (per area, from his first sessions and the family; not a diagnosis)\n"
        f"{needs_text or '(none recorded: plan from the profile)'}\n\n"
        f"# RECENT PLANS' GOALS (newest first)\n{_recent_plans_text(recent_plans)}\n\n"
        f"# GAMES (the Simon games app; trends computed from his real data)\n{games_text}\n\n"
        f"# RESEARCH NOTES (earlier findings from professional sources, newest first)\n{notes_text}\n\n"
        f"# TECHNIQUES YOU MAY USE\n{techniques_text()}"
    )


def propose_check_in_set(store, client, settings, pid, sid, context, memory_raw, known, today,
                         generate_fn) -> dict | None:
    """A new names-game set when the current one is due (12): one structured call, checked by
    code, one retry. Returns the new set (saved, the old one archived) or None -- a failure here
    never fails the plan: the game just waits for the next build."""
    bank = {_norm(w): s for w, s in MemoryDoc(word_bank=memory_raw.get("word_bank") or {}).word_bank.items()}
    prompt = context
    for attempt in (1, 2):
        try:
            result = generate_fn(
                client, _models(settings), prompt,
                types.GenerateContentConfig(system_instruction=load_prompt()["check_in_set"],
                                            response_mime_type="application/json",
                                            response_schema=CheckInProposal, temperature=0.4),
            )
            proposal = result.response.parsed
            if not isinstance(proposal, CheckInProposal):
                proposal = CheckInProposal.model_validate_json(result.response.text)
            items = enforce_set_rules(proposal, bank, known)
        except Exception as exc:  # noqa: BLE001
            _log(f"{sid}: names-game set attempt {attempt} failed: {type(exc).__name__}: {exc!s:.200}")
            prompt = (context + "\n\n# YOUR PREVIOUS SET WAS REJECTED\nUse only names from his data (memory, "
                      "profile, notes, his own words) or less-famous general places; at least 6, each with one question.")
            continue
        store.retire_check_in_set(pid)
        new = check_in_set.new_set(items, sid, today, proposal.rationale[:300])
        store.save_check_in_set(pid, new)
        _log(f"{sid}: new names-game set ({sum(i.kind == 'treated' for i in items)} treated, "
             f"{sum(i.kind != 'treated' for i in items)} untreated)")
        return new
    return None


@telemetry.job("next_plan")
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
    now: dt.datetime | None = None,
    research_fn=research_technique,
) -> str:
    """Builds and saves the next plan after session `sid`. Returns the plan_status."""
    today = today or dt.date.today()
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        memory_raw = store.get_memory(pid)
        if not memory_raw or not memory_raw.get("memory_prompt"):
            # Nothing to build on: the next session will be the intro plan.
            store.update_session(pid, sid, {"plan_status": PLAN_DONE, "plan_model": None})
            return PLAN_DONE
        # Needs checks a session didn't reach carry over (17): into the fixed second session, then one
        # per built plan. Kept with the needs, so nothing is lost if a plan is rebuilt.
        finished_session = store.get_session(pid, sid) or {}
        finished = finished_session.get("class_plan") or {}
        needs_doc = store.get_needs(pid) or {}
        pending = list(needs_doc.get("pending_checks") or [])
        for check in missed_checks(finished_session):
            if all(p.get("area") != check.get("area") for p in pending):
                pending.append(check)
        # The needs check's second session (15.5) is fixed: saved as the next plan, no LLM.
        if finished.get("plan_type") == "intro" and finished.get("intro_part") == 1:
            second = fixed_plan("intro_needs_2").model_dump(mode="json")
            second["steps"] = with_checks(second["steps"], pending)
            store.save_next_plan(pid, sid, second)
            store.save_needs(pid, {**needs_doc, "pending_checks": []})
            store.update_session(pid, sid, {"plan_status": PLAN_DONE, "plan_model": "fixed: intro_needs_2",
                                            "plan_error": None})
            _log(f"{sid}: next plan = the needs check's second session (fixed)")
            return PLAN_DONE
        notes_doc = store.get_notes(pid) or {}
        caregiver_notes = notes_doc.get("text", "")
        known = grounding_text(store, pid, memory_raw, profile_text, caregiver_notes)
        current_set = store.get_check_in_set(pid)
        recent_plans = store.recent_session_plans(pid, 5)
        seq_results, seq_task = sequencing_history(store, pid)
        seq_events = sequencing.recommended_events(seq_results)
        # Adjusting to his progress, like a therapist (17): the rules, then HIS PROGRESS for the builder.
        apply_missing_areas(store, pid, today)
        progress_text, naming_share = apply_progress(store, pid, today)
        missing_area = missing_areas.practice_turn(store.get_progress(pid), store.list_sessions(pid, 30))
        if missing_area:
            progress_text += (f"\nTHIS SESSION: a {missing_area} practice step "
                              f"({MISSING_AREA_STEPS[missing_area].TOOL}), at its level above.")
        sum_results = summarizing_history(store, pid)
        sum_ideas = summarizing.recommended_ideas(sum_results)
        discourse = discourse_turn(store, pid)
        context_args = dict(sequencing_text=render_sequencing(seq_results, seq_events, seq_task),
                            summarizing_text=render_summarizing(sum_results, sum_ideas), discourse=discourse,
                            progress_text=progress_text,
                            games_text=render_games_for_plan(games),
                            notes_text=render_notes(store.recent_technique_notes(pid, 3)),
                            caregiver_notes=caregiver_notes, pace=speaking_pace(store, pid),
                            # with an uploaded profile his needs are for the family's eyes only (Tomer, 15.10)
                            needs_text="" if account_profile(store, pid).source == "uploaded"
                            else "\n".join(needs_lines(store.get_needs(pid))))
        if check_in_set.needs_new_set(current_set, today):
            # The names game's stable set is due (none yet, or ~3 weeks / 10 sessions old): first a
            # new one, so the plan below sees which names it must not practice (12).
            set_context = build_context(memory_raw, recent_plans, profile_text, today, check_in=current_set,
                                        **context_args)
            current_set = propose_check_in_set(store, client, settings, pid, sid, set_context, memory_raw,
                                               known, today, generate_fn) or current_set
        context = build_context(memory_raw, recent_plans, profile_text, today, check_in=current_set,
                                **context_args)
        research = None
        if research_available(store, settings, pid, now):
            personal = personal_terms(memory_raw, f"{profile_text}\n{caregiver_notes}",
                                      extra=(pid.split("@")[0], games.profile if games else ""))
            research = run_research_phase(store, client, settings, pid, context, personal, now,
                                          generate_fn, research_fn)
        if research and research.get("status") in ("ok", "cached") and research.get("techniques"):
            context += (f"\n\n# RESEARCH FOR THIS PLAN (you asked: {research['question']})\n"
                        f"{research.get('summary', '')}\n{_technique_lines(research['techniques'])}")
        # The plan, built step by step with tools (13.5): each step checked when it's added, in the
        # builder's order, to a time budget at his pace.
        his_games = {g.id: g for g in (games.games if games and not games.error else [])}
        draft = PlanDraft(measured=step_minutes(store, pid))
        tools = build_plan_tools(
            draft, check_practice=practice_checker(known, check_in_set.untreated_targets(current_set)),
            his_games={gid for gid, g in his_games.items() if g.route},
            set_names={i["target"] for i in (current_set or {}).get("items") or []},
            seq_events=seq_events, seq_task=seq_task, summary_ideas=sum_ideas, discourse=discourse,
            naming_share=naming_share, missing_area=missing_area)
        run = run_tool_loop(client, _models(settings), load_prompt()["system"], context, tools,
                            max_rounds=PLAN_MAX_ROUNDS, generate_fn=generate_fn)
        if not draft.finished:
            if draft.usable() or draft.minutes() < MIN_ACCEPT * BUDGET_MINUTES:
                raise ValueError(f"the builder didn't finish a usable plan ({draft.usable() or f'~{draft.minutes()} min'};"
                                 f" {run.rounds} rounds)")
            _log(f"{sid}: plan not finished but usable (~{draft.minutes()} min, {run.rounds} rounds)")
        plan = draft.to_plan()
        # Games: homework with the Hebrew names from the catalog; suggestions saved separately (de-duplicated).
        plan = plan.model_copy(update={"game_homework": [
            h.model_copy(update={"name_he": his_games[h.game_id].name_he or h.game_id}) for h in plan.game_homework]})
        for rec in draft.games_feedback:
            store.add_games_recommendation(pid, sid, rec.model_dump(mode="json"))
        plan_dict = plan.model_dump(mode="json")
        # Measuring like a therapist (17): the story probe every other session, after the opening's next
        # step; his own view every ~2 weeks, at the end. Placed by code, the same way every time.
        recent_sessions = store.list_sessions(pid, 30)
        story = probes.story_due(recent_sessions)
        if story:
            probe = StoryProbeStep(story_id=story["id"], title=story["title"], story=" ".join(story["story"].split()),
                                   main_ideas=story["main_ideas"]).model_dump(mode="json")
            plan_dict["steps"] = [*plan_dict["steps"][:2], probe, *plan_dict["steps"][2:]]
        area_probe = None if story else missing_areas.probe_due(store.get_progress(pid), recent_sessions)
        if area_probe:  # 17.5: never in the same session as the story probe
            probe_step = AreaProbeStep(area=area_probe[0], items=[i["text"] for i in area_probe[1]]).model_dump(mode="json")
            plan_dict["steps"] = [*plan_dict["steps"][:2], probe_step, *plan_dict["steps"][2:]]
        if probes.view_due(recent_sessions, today):  # before the last two steps: the wrap-up note may come first
            cut = max(2, len(plan_dict["steps"]) - 2)
            plan_dict["steps"] = [*plan_dict["steps"][:cut], ViewStep().model_dump(mode="json"), *plan_dict["steps"][cut:]]
        if pending and account_profile(store, pid).source != "uploaded":
            plan_dict["steps"] = add_one_check(plan_dict["steps"], pending.pop(0))  # one per plan (17)
        if pending != list(needs_doc.get("pending_checks") or []):
            store.save_needs(pid, {**needs_doc, "pending_checks": pending})
        store.save_next_plan(pid, sid, {
            **plan_dict,
            "prompt_version": str(load_prompt().get("prompt_version")),
            # which version of the caregiver notes this plan saw (the page warns when they changed since)
            "notes_used_at": notes_doc.get("updated_at") if caregiver_notes.strip() else None,
            "research": ({"question": research.get("question"), "status": research.get("status"),
                          "reason": research.get("reason"),
                          "techniques": [t.get("name") for t in research.get("techniques", [])]}
                         if research else None),
        })
        model = run.models[-1] if run.models else None
        store.update_session(pid, sid, {"plan_status": PLAN_DONE, "plan_model": model, "plan_error": None,
                                        "plan_tool_calls": len(run.calls),
                                        "plan_tool_errors": sum(not c.ok for c in run.calls)})
        _log(f"{sid}: plan built ({plan.primary_goal.type.value}, {len(plan.steps)} steps, ~{plan.estimated_minutes} "
             f"min, {len(run.calls)} tool calls / {run.rounds} rounds; research "
             f"{research.get('status') if research else 'none'}; model {model})")
        return PLAN_DONE
    except Exception as exc:  # noqa: BLE001 -- recorded, retried by the sweep
        _log(f"{sid}: FAILED {type(exc).__name__}: {exc!s:.300}")
        try:
            attempts = (store.get_session(pid, sid) or {}).get("plan_attempts", 0) + 1
            store.update_session(pid, sid, {"plan_status": PLAN_FAILED, "plan_attempts": attempts,
                                            "plan_error": f"{type(exc).__name__}: {exc!s:.300}"})
        except Exception:  # noqa: BLE001
            pass
        return PLAN_FAILED
