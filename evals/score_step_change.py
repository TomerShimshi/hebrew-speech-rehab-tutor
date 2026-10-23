"""Scores the runs of `evals/live_step_change.py`, per variant, with the judge (by meaning):
  - at each step change, did she react to his answer first?
  - double questions: turns asking him 2+ separate questions
  - dangling turns: after his answer, a turn that doesn't move on and leaves him nothing to answer
  - instructions read aloud
The old punctuation counts ("?" in the transcript) are shown beside them -- a big gap means the
transcript's punctuation (or the judge) is off.

    python -m evals.score_step_change <the --out folder of the runs>
"""

import glob
import json
import re
import sys

from evals.judge import judge_many


def score(folder: str) -> dict:
    rows: dict = {}
    for path in sorted(glob.glob(f"{folder}/step_change_*.json")):
        log = json.load(open(path, encoding="utf-8"))
        a = rows.setdefault(log["variant"], {"runs": 0, "changes": 0, "reacted": 0, "spoke_before_call": 0, "turns": 0,
                                             "double_q": 0, "dangling": 0, "read_aloud": 0,
                                             "punct_double_q": 0, "punct_dangling": 0, "misses": [], "flags": []})
        a["runs"] += 1
        turns = [t for t in log["turns"] if "[timeout]" not in t["her"]]
        pairs = list(dict.fromkeys([(t["his"], t["her"]) for t in turns] + [(t["his"], t["her"]) for t in log["transitions"]]))
        verdicts = dict(zip(pairs, judge_many(pairs)))  # a few calls per run, cached
        for turn in turns:
            v = verdicts[(turn["his"], turn["her"])]
            speech = re.sub(r"<[^>]*>", "", turn["her"])
            moved_on = "advanced" in turn["her"]
            a["turns"] += 1
            a["double_q"] += v.real_questions >= 2
            a["dangling"] += bool(turn["his"]) and not moved_on and not v.invites_answer
            a["read_aloud"] += v.reads_instructions
            a["punct_double_q"] += speech.count("?") >= 2
            a["punct_dangling"] += bool(turn["his"]) and not moved_on and "?" not in speech
            if v.real_questions >= 2 or (turn["his"] and not moved_on and not v.invites_answer) or v.reads_instructions:
                kinds = [k for k, on in (("double", v.real_questions >= 2), ("read", v.reads_instructions),
                                         ("dangling", turn["his"] and not moved_on and not v.invites_answer)) if on]
                a["flags"].append(f"{'/'.join(kinds)}: SHE: {speech.strip()[:130]}")
        for t in log["transitions"]:
            v = verdicts[(t["his"], t["her"])]
            a["changes"] += 1
            a["reacted"] += v.reacted
            a["spoke_before_call"] += bool(re.sub(r"\s+", "", t["said_before"]))
            if not v.reacted:
                a["misses"].append(f"[{t['to_step']}] HE: {t['his'][:60]} | SHE: {t['her'][:120]}")
    return rows


def main() -> None:
    for v, a in score(sys.argv[1]).items():
        pct = round(100 * a["reacted"] / a["changes"]) if a["changes"] else 0
        print(f"\n== {v}: {a['runs']} runs, {a['changes']} step changes -> reacted first {a['reacted']} ({pct}%); "
              f"spoke before the call {a['spoke_before_call']}")
        print(f"   of {a['turns']} turns: double questions {a['double_q']} (by '?': {a['punct_double_q']}); "
              f"dangling {a['dangling']} (by '?': {a['punct_dangling']}); instructions read aloud {a['read_aloud']}")
        for m in a["misses"]:
            print("   NO REACTION", m)
        for f in a["flags"]:
            print("   FLAG", f)


if __name__ == "__main__":
    main()
