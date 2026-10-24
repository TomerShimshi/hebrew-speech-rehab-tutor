"""Before / after on REAL sessions: the conversation-quality issues measured on an account's past
sessions (the baseline) and on the sessions after a fix (N+1, N+2, ...) -- the same measures, so a fix
is judged by his real sessions, not by text-mode runs.

Per session:
  - step changes where her first words didn't react to his answer       (the judge)
  - double questions -- turns asking him 2+ separate questions          (the judge, every turn)
  - dangling turns -- after his answer, nothing for him to answer         (the judge)
  - instructions read aloud                                              (the judge)
  - a greeting (her first turn) with more than one question               (the judge)
  - repeated questions -- a question she already asked and he answered    (code: word overlap)

    python -m evals.session_metrics --account <email> --sessions 12 --split-version 3.6
    python -m evals.session_metrics --account <email> --sessions 12 --split-date 2026-10-24

Credit: the judge is batched and cached (evals/judge.py) -- a first run costs ~1 call per 15 turns,
reruns are free. Prints to the terminal only (nothing personal is saved).
"""

import argparse
import re

from app.store import FirestoreSessionStore
from evals.judge import judge_many

REPEAT_OVERLAP = 0.7  # a question sharing 70%+ of its words with an earlier one is a repeat


def _words(text: str) -> set[str]:
    return {w for w in re.sub(r"[^\w\s]", " ", text or "").split() if len(w) > 1}


def _questions(text: str) -> list[str]:
    return [q.strip() for q in re.findall(r"[^.!?]*\?", text or "") if len(_words(q)) >= 3]


def step_kind_at(session: dict, t_s: float) -> str:
    """The kind of the step that was current at t_s seconds into the session (from steps_done)."""
    agenda = session.get("agenda") or []
    i = sum(1 for d in session.get("steps_done") or [] if d.get("at_s", 0) <= t_s + 1)
    return agenda[i]["kind"] if i < len(agenda) else "after"


def repeated_questions(turns: list[dict], session: dict | None = None) -> list[tuple[int, str]]:
    """Her questions that repeat an earlier one of hers, after he had answered in between, as
    (index of the turn, the question). Not inside the names game: asking an item again after a
    miss is the game (23.10: 4 of the patient's 6 "repeats" were that)."""
    asked: list[tuple[set[str], int, str]] = []  # (words, index of the turn, step kind)
    repeats = []
    for i, t in enumerate(turns):
        if t["speaker"] != "tutor" or t.get("not_played"):
            continue
        kind = step_kind_at(session, t.get("t_start_s", 0)) if session else ""
        for q in _questions(t.get("text", "")):
            w = _words(q)
            for prev, j, prev_kind in asked:
                answered = any(x["speaker"] == "patient" for x in turns[j + 1:i])
                if answered and len(w & prev) / max(1, min(len(w), len(prev))) >= REPEAT_OVERLAP:
                    if not (kind == prev_kind == "names_game"):
                        repeats.append((i, q[:90]))
                    break
            asked.append((w, i, kind))
    return repeats


def session_rows(store, pid: str, sid: str, session: dict) -> tuple[list, dict]:
    """The (his, her) turns to judge, and what each one is: a step change, the greeting, ..."""
    turns = session_turns(store, pid, sid)
    rows, kinds = [], []
    last_his = ""
    first = True
    for i, t in enumerate(turns):
        if t["speaker"] == "patient":
            last_his = t["text"]
            continue
        if t.get("not_played"):
            continue
        rows.append((last_his, t["text"]))
        kinds.append({"greeting": first, "after_answer": bool(last_his), "t": t.get("t_start_s", 0), "i": i})
        first = False
    # step changes: her first turn starting after each next_step report
    for d in session.get("steps_done") or []:
        at = d.get("at_s", 0)
        idx = next((k for k, kd in enumerate(kinds) if kd["t"] >= at - 1), None)
        if idx is not None:
            kinds[idx]["step_change"] = True
    return rows, {"kinds": kinds, "repeats": repeated_questions(turns, session)}


def session_turns(store, pid: str, sid: str) -> list[dict]:
    """The session's turns with text, in order (the indices the flagged points refer to)."""
    return [t for t in store.list_turns(pid, sid) if t.get("text")]


def measure(store, pid: str, sessions: list[dict]) -> dict:
    rows_all, meta_all = [], []
    for s in sessions:
        rows, meta = session_rows(store, pid, s["id"], s)
        rows_all.append(rows)
        meta_all.append(meta)
    verdicts = judge_many([r for rows in rows_all for r in rows])  # batched, cached
    out = {"sessions": len(sessions), "step_changes": 0, "no_reaction": 0, "turns": 0, "double_q": 0,
           "dangling": 0, "read_aloud": 0, "greetings": 0, "greeting_double": 0, "repeated": 0, "examples": [],
           "points": []}  # the flagged turns, for evals/replay_turns.py: {sid, i, issue}
    k = 0
    for s, rows, meta in zip(sessions, rows_all, meta_all):
        for (his, her), kind in zip(rows, meta["kinds"]):
            v = verdicts[k]
            k += 1
            out["turns"] += 1
            out["double_q"] += v.real_questions >= 2
            out["read_aloud"] += v.reads_instructions
            if v.real_questions >= 2:
                out["points"].append({"sid": s["id"], "i": kind["i"], "issue": "double_q"})
            if kind.get("step_change") and not v.reacted:
                out["points"].append({"sid": s["id"], "i": kind["i"], "issue": "no_reaction"})
            if kind["after_answer"] and not v.invites_answer and not kind.get("step_change"):
                out["dangling"] += 1
            if kind["greeting"]:
                out["greetings"] += 1
                out["greeting_double"] += v.real_questions >= 2
            if kind.get("step_change"):
                out["step_changes"] += 1
                if not v.reacted:
                    out["no_reaction"] += 1
                    out["examples"].append(f"no reaction | HE: {his[:50]} | SHE: {her[:80]}")
        out["repeated"] += len(meta["repeats"])
        out["examples"] += [f"repeated | {q}" for _, q in meta["repeats"]]
        out["points"] += [{"sid": s["id"], "i": i, "issue": "repeated"} for i, _ in meta["repeats"]]
    return out


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({round(100 * n / d)}%)" if d else "-"


def report(name: str, m: dict) -> None:
    print(f"\n== {name}: {m['sessions']} sessions, {m['turns']} turns")
    print(f"   no reaction at a step change : {_pct(m['no_reaction'], m['step_changes'])}")
    print(f"   double questions             : {_pct(m['double_q'], m['turns'])}")
    print(f"   greeting with 2+ questions   : {_pct(m['greeting_double'], m['greetings'])}")
    print(f"   dangling turns               : {_pct(m['dangling'], m['turns'])}")
    print(f"   instructions read aloud      : {_pct(m['read_aloud'], m['turns'])}")
    print(f"   repeated questions           : {m['repeated']} ({round(m['repeated'] / m['sessions'], 2) if m['sessions'] else 0} a session)")


def load_sessions(store, pid: str, n: int, min_version: str = "3.3") -> list[dict]:
    """The account's last n ended sessions that ran with steps (newest first)."""
    sessions = [store.get_session(pid, s["id"]) | {"id": s["id"]} for s in store.list_sessions(pid, n)]
    return [s for s in sessions if s.get("status") == "ended" and (s.get("prompt_version") or "") >= min_version
            and s.get("steps_done")]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--account", required=True)
    ap.add_argument("--sessions", type=int, default=12)
    ap.add_argument("--split-version", help="sessions on this tutor prompt version or later are 'after'")
    ap.add_argument("--split-date", help="sessions on this date (YYYY-MM-DD) or later are 'after'")
    ap.add_argument("--min-version", default="3.3", help="leave out older sessions (another way of running)")
    ap.add_argument("--examples", action="store_true", help="print the flagged turns (to the terminal only)")
    args = ap.parse_args()
    store = FirestoreSessionStore()
    sessions = load_sessions(store, args.account, args.sessions, args.min_version)

    def after(s):
        if args.split_version:
            return (s.get("prompt_version") or "") >= args.split_version
        if args.split_date:
            return str(s.get("started_at"))[:10] >= args.split_date
        return False

    groups = {"before": [s for s in sessions if not after(s)], "after": [s for s in sessions if after(s)]}
    for name, group in groups.items():
        if group:
            m = measure(store, args.account, group)
            report(f"{name} ({str(group[-1].get('started_at'))[:10]} .. {str(group[0].get('started_at'))[:10]})", m)
            if args.examples:
                for e in m["examples"]:
                    print("     ", e)


if __name__ == "__main__":
    main()
