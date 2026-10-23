"""Audit of REAL sessions: at each step change (from the session's steps_done), did her first words
react to his answer? The check to run after a prompt change, on the sessions since.

    python -m evals.audit_step_changes --account <email> [--sessions 5] [--since 3.5]

Prints counts and the misses (his answer, her first words) -- to the terminal only.
"""

import argparse

from app.store import FirestoreSessionStore
from evals.judge import judge_many


def audit(store, pid: str, n: int, since: str) -> tuple[int, int, list[str]]:
    rows = []  # (his, her, label) at each step change
    for s in store.list_sessions(pid, n):
        f = store.get_session(pid, s["id"]) or {}
        if (f.get("prompt_version") or "") < since:
            continue
        turns = [t for t in store.list_turns(pid, s["id"]) if t.get("text")]
        agenda = f.get("agenda") or []
        for i, d in enumerate(f.get("steps_done") or []):
            at = d.get("at_s", 0)
            his = [t for t in turns if t["speaker"] == "patient" and t.get("t_start_s", 0) <= at + 1][-1:]
            her = next((t for t in turns if t["speaker"] == "tutor" and t.get("t_start_s", 0) >= at - 1), None)
            if his and her:
                to = agenda[i + 1]["kind"] if i + 1 < len(agenda) else "after"
                rows.append((his[0]["text"], her["text"], f"{str(f.get('started_at'))[:16]} [{to}]"))
    verdicts = judge_many([(h, s) for h, s, _ in rows])  # batched, cached
    misses = [f"{label} HE: {h[:60]} | SHE: {s[:110]}" for (h, s, label), v in zip(rows, verdicts) if not v.reacted]
    return len(rows), sum(v.reacted for v in verdicts), misses


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--account", required=True)
    ap.add_argument("--sessions", type=int, default=5)
    ap.add_argument("--since", default="", help="only sessions with this tutor prompt version or later, e.g. 3.5")
    args = ap.parse_args()
    total, reacted, misses = audit(FirestoreSessionStore(), args.account, args.sessions, args.since)
    print(f"{total} step changes, reacted first in {reacted} ({round(100 * reacted / total) if total else 0}%)")
    for m in misses:
        print("  MISS", m)


if __name__ == "__main__":
    main()
