"""Telling things in order (sub-plan 14): plain code, no LLM.

  scramble()           the order she says the events in (`scrambled`): never the original, never the
                       reverse, at most one pair still next to each other in the right order
  score()              how well he told them: the share of neighbouring pairs in the right order, and
                       how many events he included
  recommended_events() the next task's size, from his recent results
"""

import hashlib
import random

MIN_EVENTS, MAX_EVENTS, DEFAULT_EVENTS = 3, 6, 4


def _in_order_pairs(order: list[int]) -> int:
    return sum(1 for a, b in zip(order, order[1:]) if b == a + 1)


def scramble(n: int, seed: str = "") -> list[int]:
    """A scrambled order of events 1..n -- deterministic for the same story (the seed), so a plan
    always shows the same order."""
    rng = random.Random(int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8], 16))
    original, reverse = list(range(1, n + 1)), list(range(n, 0, -1))
    for _ in range(500):
        order = original[:]
        rng.shuffle(order)
        if order not in (original, reverse) and _in_order_pairs(order) <= 1:
            return order
    raise ValueError(f"can't scramble {n} events")


def score(told: list[int], n: int) -> dict:
    """`told`: the events' numbers (1..n, the correct order) in the order he told them; events he
    left out are simply absent. [1,3,2,4,5] -> 1->3 ok, 3->2 no, 2->4 ok, 4->5 ok = 3 of 4 = 75%."""
    seen, order = set(), []
    for t in told:
        if isinstance(t, int) and 1 <= t <= n and t not in seen:
            seen.add(t)
            order.append(t)
    pairs = len(order) - 1
    right = sum(1 for a, b in zip(order, order[1:]) if b > a)
    return {"order_pct": round(100 * right / pairs) if pairs > 0 else 0, "events_included": len(order),
            "events": n, "full": len(order) == n and right == pairs}


def recommended_events(history: list[dict]) -> int:
    """`history`: his recent results, newest first ({events, order_pct, full}). Full marks twice in
    a row -> one more (up to 6); under half -> one fewer (down to 3); otherwise the same."""
    if not history:
        return DEFAULT_EVENTS
    last = history[0]
    n = int(last.get("events") or DEFAULT_EVENTS)
    if len(history) >= 2 and last.get("full") and history[1].get("full"):
        return min(MAX_EVENTS, n + 1)
    if (last.get("order_pct") or 0) < 50:
        return max(MIN_EVENTS, n - 1)
    return n
