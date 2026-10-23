"""Checks the judge against hand-labeled cases (evals/judge_cases.yaml): agreement per field, and the
cases it gets wrong. Run after changing prompts/eval_judge.yaml or the judge model.

    python -m evals.check_judge
"""

from pathlib import Path

import yaml

from evals.judge import judge_many, prompt

CASES = Path(__file__).with_name("judge_cases.yaml")


def main() -> None:
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))["cases"]
    right: dict[str, int] = {}
    total: dict[str, int] = {}
    wrong = []
    verdicts = judge_many([(c["his"], c["her"]) for c in cases])  # one call (cached after)
    for c, verdict in zip(cases, verdicts):
        v = verdict.model_dump()
        for field, expected in c["expect"].items():
            total[field] = total.get(field, 0) + 1
            if v[field] == expected:
                right[field] = right.get(field, 0) + 1
            else:
                wrong.append(f"{c['name']}: {field} = {v[field]} (expected {expected})")
    print(f"judge prompt {prompt().get('prompt_version')}, {len(cases)} cases")
    for field in total:
        print(f"  {field}: {right.get(field, 0)}/{total[field]}")
    for w in wrong:
        print("  WRONG", w)


if __name__ == "__main__":
    main()
