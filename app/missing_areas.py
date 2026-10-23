"""Practicing the missing areas -- repetition, understanding, clarity -- once a difficulty is confirmed
(sub-plan 17.5): plain code, no LLM.

  status()        confirming first: seen once -> re-checked -> confirmed / not confirmed (from the needs'
                  per-session history; the family's word wins)
  hand_over()     a confirmed area joins 17's progress rules at level 1, less time
  practice_turn() which area (at most one) gets a practice step in the next plan
  probe_due()     which area gets a measurement on its fixed bank in the next plan
  score()         a measurement's result, by code from what the memory agent heard
"""

import re
from functools import lru_cache

import yaml

from app.config import REPO_ROOT

AREAS = ("repetition", "understanding", "clarity")
DIFFICULT = ("some_difficulty", "clear_difficulty")
WINDOW = 3  # confirmed: a difficulty in 2 of the 3 sessions that showed the area
PROBE_EVERY = 3  # a measurement every ~3rd session while the area is practiced
PROBE_ITEMS = 4
PRACTICE_KINDS = {"repetition": "repetition", "understanding": "understanding", "clarity": "clarity"}


@lru_cache
def bank(area: str) -> list[dict]:
    """The area's fixed measurement items: {level, text, answer}."""
    path = REPO_ROOT / "prompts" / f"probe_{area}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))["items"]


# ---- confirming first -----------------------------------------------------------------------------

def status(area_doc: dict | None) -> str:
    """'fine' | 'seen_once' | 'rechecking' | 'confirmed' | 'not_confirmed'. From the levels the app
    recorded per session (15.5), in windows: a difficulty opens a window of 3 sessions that showed the
    area; 2 difficulties in it confirm it, otherwise it's not confirmed (and a later difficulty opens
    a new window). Confirmed stays confirmed. The family's status wins."""
    a = area_doc or {}
    if a.get("family_status") in ("confirmed", "not_confirmed"):
        return a["family_status"]
    levels = [h.get("level") for h in a.get("history") or []]
    result, p = "fine", 0
    while p < len(levels):
        if levels[p] not in DIFFICULT:
            p += 1
            continue
        window = levels[p:p + WINDOW]
        hard = sum(1 for lv in window if lv in DIFFICULT)
        if hard >= 2:
            return "confirmed"
        if len(window) < WINDOW:
            return "seen_once" if len(window) == 1 else "rechecking"
        result, p = "not_confirmed", p + WINDOW
    return result


def recheck_step(area: str, n: int = 0) -> dict:
    """A light re-check inside the talk: a CheckStep (15.5) with two bank items (rotating by `n`)."""
    items = bank(area)
    if area == "understanding":
        yes_no = [i for i in items if i["level"] <= 2]
        request = [i for i in items if i["level"] == 4]
        chosen = [yes_no[n % len(yes_no)]["text"], request[n % len(request)]["text"]]
    else:
        easy = [i for i in items if i["level"] <= 2] or items
        chosen = [easy[(2 * n + k) % len(easy)]["text"] for k in range(2)]
    return {"kind": "check", "area": area, "items": chosen}


# ---- after confirmation: 17's progress rules -------------------------------------------------------

def hand_over(progress_doc: dict, area: str, today: str, by: str = "app") -> dict:
    """The area joins the progress rules (17) at level 1, less time -- the gradual start. Logged."""
    areas = dict(progress_doc.get("areas") or {})
    if (areas.get(area) or {}).get("active"):
        return progress_doc
    areas[area] = {"level": 1, "share": "less", "seen": 0, "active": True, "change_approach": False}
    log = [*(progress_doc.get("log") or []), {"date": today, "area": area, "rule": "confirmed", "by": by,
                                              "reason": "a difficulty in 2 of 3 sessions -- practice starts small",
                                              "to": {"level": 1, "share": "less"}}]
    return {**progress_doc, "areas": areas, "log": log[-60:]}


def _regular(sessions: list[dict]) -> list[dict]:
    return [s for s in sessions if s.get("status") == "ended" and (s.get("class_plan") or {}).get("plan_type") == "regular"]


def _sessions_since(sessions: list[dict], has) -> int:
    regular = _regular(sessions)  # newest first
    return next((i for i, s in enumerate(regular) if has(s)), len(regular) + 99)


def practice_turn(progress_doc: dict | None, sessions: list[dict]) -> str | None:
    """At most ONE of these areas per session: the most overdue active area whose dose says it's due --
    'less': every other session, 'normal' / 'more': every session. Locked areas still practice."""
    best, best_gap = None, -1
    for area in AREAS:
        st = ((progress_doc or {}).get("areas") or {}).get(area) or {}
        if not st.get("active"):
            continue
        gap = _sessions_since(sessions, lambda s, a=area: any(
            x.get("kind") == a for x in (s.get("class_plan") or {}).get("steps") or []))
        need = 2 if st.get("share") == "less" else 1
        if gap + 1 >= need and gap > best_gap:
            best, best_gap = area, gap
    return best


def probe_due(progress_doc: dict | None, sessions: list[dict]) -> tuple[str, list[dict]] | None:
    """(area, items) when an active area's measurement is due: right after confirmation (the baseline),
    then every ~3rd session. One per session; the items rotate through the fixed bank."""
    for area in AREAS:
        st = ((progress_doc or {}).get("areas") or {}).get(area) or {}
        if not st.get("active"):
            continue
        done = [s for s in _regular(sessions) if (s.get("area_probe") or {}).get("area") == area]
        gap = _sessions_since(sessions, lambda s, a=area: (s.get("area_probe") or {}).get("area") == a)
        if done and gap + 1 < PROBE_EVERY:
            continue
        return area, probe_items(area, len(done))
    return None


def probe_items(area: str, k: int) -> list[dict]:
    """The k-th measurement's items: the SAME mix of levels every time (comparable scores) -- the top
    levels when the bank has more levels than items -- rotating only within each level."""
    items = bank(area)
    levels = sorted({i["level"] for i in items})[-PROBE_ITEMS:]
    by_level = {lv: [i for i in items if i["level"] == lv] for lv in levels}
    chosen, used = [], {}
    for n in range(PROBE_ITEMS):
        lv = levels[n % len(levels)]
        group = by_level[lv]
        per_probe = sum(1 for m in range(PROBE_ITEMS) if levels[m % len(levels)] == lv)
        chosen.append(group[(k * per_probe + used.get(lv, 0)) % len(group)])
        used[lv] = used.get(lv, 0) + 1
    return chosen


# ---- scoring by code ----------------------------------------------------------------------------------

def _words(text: str) -> list[str]:
    return [w for w in re.sub(r"[^\w\s]", " ", text or "").split() if w]


def word_match(said: str, target: str) -> float:
    """The share of the target's words he said (in any order) -- repetition and clarity."""
    t, s = _words(target), set(_words(said))
    return sum(1 for w in t if w in s) / len(t) if t else 0.0


def score(area: str, items: list[dict], reported: dict | None) -> dict | None:
    """The measurement's result: per item 0..1 (words matched, or right / wrong), and the area's %."""
    base = {"area": area, "items": len(items)}
    if not reported:
        return {**base, "status": "not_reported"}
    if reported.get("skipped"):
        return {**base, "status": "skipped"}
    per = []
    for r in reported.get("results") or []:
        i = r.get("item")
        if not isinstance(i, int) or not 1 <= i <= len(items):
            continue
        if area == "understanding":
            per.append(1.0 if r.get("correct") else 0.0)
        else:
            per.append(word_match(str(r.get("said", "")), items[i - 1]["text"]))
    if not per:
        return {**base, "status": "not_reported"}
    return {**base, "status": "done", "pct": round(100 * sum(per) / len(items)), "answered": len(per),
            "low_confidence": bool(reported.get("low_confidence"))}
