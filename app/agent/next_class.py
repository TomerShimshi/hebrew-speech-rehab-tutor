"""Next-class builder (SUMMARY_MODEL call #3): updated memory -> the next session's ClassPlan.

Two phases (07):
  1. optional research: a short tool loop with one tool, research_technique(question), offered
     only when research is possible (Tavily key, daily/monthly budget). At most one research
     run per plan; any failure here is ignored -- research is an extra.
  2. one structured-output call: everything in the context (plus the research, and recent
     research notes), output a validated plan.
Runs right after a successful memory update (and from the hourly sweep). Never raises:
failures are recorded as plan_status.
"""

import datetime as dt
import re
import sys
from functools import lru_cache

import yaml
from google.genai import types

from app import word_bank
from app.agent.memory_update import format_memory
from app.agent.research import personal_terms, research_technique
from app.agent.runner import Tool, run_tool_loop
from app.config import REPO_ROOT, Settings
from app.games import render_games_for_plan
from app.llm import generate
from app.schemas import ClassPlan, MemoryDoc
from app.store import PLAN_DONE, PLAN_FAILED, SessionStore

PROMPT_PATH = REPO_ROOT / "prompts" / "next_class.yaml"
TECHNIQUES_PATH = REPO_ROOT / "prompts" / "therapy_techniques.yaml"
MIN_PROBE_ITEMS = 3
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
    return bool(getattr(item, "about_his_life", False) or PERSONAL.search(f"{item.elicit} {getattr(item, 'bridge', '')}"))


def _grounded(target: str, known: str) -> bool:
    # Hebrew attaches prefixes to words: "ברמת גן", "והירקון", "מחיפה" all count for the name.
    name = _plain(target)
    return bool(name) and re.search(rf"(?<!\w)[בהולמשכ]{{0,2}}{re.escape(name)}(?!\w)", known) is not None


def invented_items(plan: ClassPlan, known: str) -> list[str]:
    return [i.target for i in [*plan.probe, *plan.practice] if _about_his_life(i) and not _grounded(i.target, known)]


def enforce_plan_rules(plan: ClassPlan, practiced: set[str], known: str | None = None) -> ClassPlan:
    """Rules the model sometimes ignores (seen with the smallest fallback model), fixed by code:
    check-in items are classified treated/untreated from the word bank, too-famous NEW items are
    dropped, and practice never repeats a check-in item (it would spoil the untreated
    comparison and thin out the session). Items about HIS OWN life whose answer isn't in his own
    data (`known`, from grounding_text) are dropped: the plan must never invent his people
    (8.5). Raises if what's left is too thin to use."""
    if known is not None:
        invented = [i for i in [*plan.probe, *plan.practice] if _about_his_life(i) and not _grounded(i.target, known)]
        if invented:
            _log(f"dropped {len(invented)} item(s) about his life not found in his data: {[i.target for i in invented]}")
            plan = plan.model_copy(update={
                "probe": [i for i in plan.probe if i not in invented],
                "practice": [i for i in plan.practice if i not in invented],
            })
    probe = []
    for p in plan.probe:
        treated = _norm(p.target) in practiced
        if not treated and _norm(p.target) in TOO_FAMOUS:
            _log(f"dropped too-famous check-in item {p.target!r}")
            continue
        probe.append(p.model_copy(update={"kind": "treated" if treated else "untreated"}))
    probe_targets = {_norm(p.target) for p in probe} | {_norm(p.target) for p in plan.probe}
    practice = [p for p in plan.practice if _norm(p.target) not in probe_targets]
    if len(practice) < len(plan.practice):
        _log(f"dropped {len(plan.practice) - len(practice)} practice items that repeat check-in items")
    if len(probe) < MIN_PROBE_ITEMS:
        # Without check-in items there's no progress measurement: don't accept it.
        raise ValueError(f"plan has {len(probe)} usable probe items (need {MIN_PROBE_ITEMS}+)")
    if plan.primary_goal.type.value == "name_retrieval" and plan.practice and not practice:
        raise ValueError("every practice item repeats a check-in item")
    return plan.model_copy(update={"probe": probe, "practice": practice})


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
    return bool(settings.tavily_api_key
                and store.research_runs_on(pid, now.date().isoformat()) < settings.research_daily_limit
                and store.searches_in_month(now.strftime("%Y-%m")) < settings.research_monthly_limit)


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

    tool = Tool(
        name="research_technique",
        description=("Look up evidence-based home-practice techniques (professional sources) for ONE "
                     "generic clinical question in English. Never include names, places or Hebrew."),
        parameters={"type": "object", "properties": {"question": {"type": "string", "description":
                    "e.g. 'mild anomia for proper names in a fluent speaker; retrieval practice at home'"}},
                    "required": ["question"]},
        handler=handle,
    )
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


def build_context(memory_raw: dict, recent_plans: list[dict], profile_text: str, today: dt.date,
                  games_text: str = "(no games account linked)", notes_text: str = "(none yet)",
                  caregiver_notes: str = "") -> str:
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
        f"# NOTES FROM THE FAMILY / THERAPIST (follow them; they override the memory)\n"
        f"{caregiver_notes.strip() or '(none)'}\n\n"
        f"# MEMORY (what the tutor knows about him)\n{memory.memory_prompt}\n\n"
        f"# MEMORY SECTIONS\n{format_memory(memory)}\n\n"
        f"# FOCUS POINTS FROM THE LAST SESSION\n" + ("\n".join(f"- {f}" for f in memory.focus_next_session) or "(none)") + "\n\n"
        f"# WORD BANK\ndue for practice today: {', '.join(due) or '(none)'}\nall recent: {bank}\n\n"
        f"# RECENT SESSIONS (oldest first)\n{recent}\n\n"
        f"# RECENT PLANS' GOALS (newest first)\n{_recent_plans_text(recent_plans)}\n\n"
        f"# GAMES (the Simon games app; trends computed from his real data)\n{games_text}\n\n"
        f"# RESEARCH NOTES (earlier findings from professional sources, newest first)\n{notes_text}\n\n"
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
        notes_doc = store.get_notes(pid) or {}
        caregiver_notes = notes_doc.get("text", "")
        context = build_context(memory_raw, store.recent_session_plans(pid, 5), profile_text, today,
                                games_text=render_games_for_plan(games),
                                notes_text=render_notes(store.recent_technique_notes(pid, 3)),
                                caregiver_notes=caregiver_notes)
        research = None
        if research_available(store, settings, pid, now):
            personal = personal_terms(memory_raw, f"{profile_text}\n{caregiver_notes}",
                                      extra=(pid.split("@")[0], games.profile if games else ""))
            research = run_research_phase(store, client, settings, pid, context, personal, now,
                                          generate_fn, research_fn)
        if research and research.get("status") in ("ok", "cached") and research.get("techniques"):
            context += (f"\n\n# RESEARCH FOR THIS PLAN (you asked: {research['question']})\n"
                        f"{research.get('summary', '')}\n{_technique_lines(research['techniques'])}")
        # treated/untreated drives the progress comparison, so it's decided by code, not the
        # model: an item is "treated" only if it's actually in his word bank.
        practiced = {_norm(w) for w in (memory_raw.get("word_bank") or {})}
        known = grounding_text(store, pid, memory_raw, profile_text, caregiver_notes)
        for attempt in (1, 2):
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
            invented = invented_items(plan, known)
            try:
                plan = enforce_plan_rules(plan, practiced, known)
                break
            except ValueError:
                if attempt == 2 or not invented:
                    raise
                # One more try, told exactly what was invented (8.5).
                _log(f"{sid}: plan invented {invented}; retrying once")
                context += (f"\n\n# YOUR PREVIOUS PLAN WAS REJECTED\nThese answers are not in his data -- you "
                            f"invented them: {', '.join(invented)}. Never use them. Use only names that appear in "
                            f"the memory, profile or notes, or well-known general items; if names of his people "
                            f"are missing, make the activity COLLECT them by asking him, and fill the remaining check-ins "
                            f"with known items of another kind (see PRIORITY).")
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
        store.save_next_plan(pid, sid, {
            **plan.model_dump(mode="json"),
            "prompt_version": str(load_prompt().get("prompt_version")),
            # which version of the caregiver notes this plan saw (the page warns when they changed since)
            "notes_used_at": notes_doc.get("updated_at") if caregiver_notes.strip() else None,
            "research": ({"question": research.get("question"), "status": research.get("status"),
                          "reason": research.get("reason"),
                          "techniques": [t.get("name") for t in research.get("techniques", [])]}
                         if research else None),
        })
        store.update_session(pid, sid, {"plan_status": PLAN_DONE, "plan_model": result.model, "plan_error": None})
        _log(f"{sid}: plan built ({plan.primary_goal.type.value}, {len(plan.probe)} probe, "
             f"{len(plan.practice)} practice; research {research.get('status') if research else 'none'}; "
             f"model {result.model})")
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
