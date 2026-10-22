"""Summarizing a short text in his own words (sub-plan 17; ARCS-style, by voice): plain code, no LLM.

  score()             how much of the paragraph he conveyed: the share of its main ideas
  recommended_ideas() the next paragraph's size, from his recent results
"""

MIN_IDEAS, MAX_IDEAS, DEFAULT_IDEAS = 3, 6, 4


def score(conveyed: list[int], n: int) -> dict:
    """`conveyed`: the numbers (1..n) of the main ideas he conveyed in his own words."""
    got = {c for c in conveyed if isinstance(c, int) and 1 <= c <= n}
    return {"ideas_pct": round(100 * len(got) / n) if n else 0, "ideas_conveyed": len(got), "ideas": n,
            "full": n > 0 and len(got) == n}


def recommended_ideas(history: list[dict]) -> int:
    """`history`: his recent results, newest first ({ideas, ideas_pct, full}). All the ideas twice in a
    row -> one more (up to 6); under half -> one fewer (down to 3); otherwise the same -- like the
    sequencing task's size (14)."""
    if not history:
        return DEFAULT_IDEAS
    last = history[0]
    n = int(last.get("ideas") or DEFAULT_IDEAS)
    if len(history) >= 2 and last.get("full") and history[1].get("full"):
        return min(MAX_IDEAS, n + 1)
    if (last.get("ideas_pct") or 0) < 50:
        return max(MIN_IDEAS, n - 1)
    return n
