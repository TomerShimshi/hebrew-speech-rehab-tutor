"""The names game's stable check-in set (sub-plan 12): plain code, no LLM.

A set is 6-10 names (treated = practiced in the word bank, untreated = never practiced), each
with ONE fixed question. It stays for about three weeks, so the same names are asked the same
way and the trend means something. Each session asks a few of them, in rotation; the plan
builder proposes the next set when this one is due (app/agent/next_class.py).

  patients/{pid}/plans/check_in = {
    id, created_on, created_after_session, rationale, sessions_played,
    items: [{target, question, kind, about_his_life, asked, last_asked, results: [...]}],
  }
"""

import datetime as dt

from app.schemas import CheckInItem, ProbeItem

SET_DAYS = 21  # a set is replaced after about three weeks...
SET_SESSIONS = 10  # ...or this many sessions with the game, whichever comes first
PER_SESSION = 3  # names asked in one session
MAX_RESULTS = 30  # per name, kept for the caregiver page


def _norm(text: str) -> str:
    return " ".join((text or "").split()).strip()


def new_set(items: list[CheckInItem], sid: str, today: dt.date, rationale: str = "") -> dict:
    return {
        "id": f"{today.isoformat()}-{sid[:8]}",
        "created_on": today.isoformat(),
        "created_after_session": sid,
        "rationale": rationale,
        "sessions_played": 0,
        "items": [{**i.model_dump(), "asked": 0, "last_asked": None, "results": []} for i in items],
    }


def needs_new_set(current: dict | None, today: dt.date) -> bool:
    if not current or not current.get("items"):
        return True
    age = (today - dt.date.fromisoformat(current["created_on"])).days
    return age >= SET_DAYS or current.get("sessions_played", 0) >= SET_SESSIONS


def choose_items(current: dict | None, n: int = PER_SESSION) -> list[dict]:
    """The least recently asked names first, mixing treated and untreated when both exist.
    A skipped game asks nothing, so the same names simply come up again next time."""
    items = list((current or {}).get("items") or [])
    order = sorted(range(len(items)), key=lambda i: (items[i].get("last_asked") or "", items[i].get("asked", 0), i))
    chosen = [items[i] for i in order[:n]]
    kinds = {c.get("kind") for c in chosen}
    if len(chosen) >= 2 and len(kinds) == 1:
        other = next((items[i] for i in order[n:] if items[i].get("kind") not in kinds), None)
        if other is not None:
            chosen[-1] = other
    return chosen


def probe_items(chosen: list[dict]) -> list[ProbeItem]:
    """As the plan's check-in items, so the memory update scores them as before."""
    return [ProbeItem(target=c["target"], kind=c.get("kind", "untreated"), elicit=c["question"],
                      about_his_life=c.get("about_his_life", False)) for c in chosen]


def untreated_targets(current: dict | None) -> set[str]:
    return {_norm(i["target"]) for i in (current or {}).get("items") or [] if i.get("kind") != "treated"}


def record_results(current: dict, probe_results: list[dict], sid: str, today: dt.date) -> bool:
    """Adds this session's names-game answers to the set. Returns True if any belonged to it."""
    by_target = {_norm(i["target"]): i for i in current.get("items") or []}
    played = False
    for r in probe_results:
        item = by_target.get(_norm(r.get("word", "")))
        if item is None:
            continue
        played = True
        item["asked"] = item.get("asked", 0) + 1
        item["last_asked"] = today.isoformat()
        item["results"] = [*item.get("results", []), {
            "date": today.isoformat(), "session_id": sid, "result": r.get("result"),
            "low_confidence": bool(r.get("low_confidence")),
        }][-MAX_RESULTS:]
    if played:
        current["sessions_played"] = current.get("sessions_played", 0) + 1
    return played


def correct_result(current: dict, sid: str, target: str, result: str) -> bool:
    """This session's result for a name, corrected from the recording (the live one kept as
    live_result). Returns True if it changed."""
    item = next((i for i in current.get("items") or [] if _norm(i["target"]) == _norm(target)), None)
    entry = next((r for r in reversed((item or {}).get("results") or []) if r.get("session_id") == sid), None)
    if entry is None or entry.get("result") == result:
        return False
    entry.setdefault("live_result", entry.get("result"))
    entry["result"] = result
    entry["rechecked"] = True
    return True


def _last_asked(item: dict) -> str | None:
    return max((r.get("date") for r in item.get("results") or [] if r.get("date")), default=None)


def remove_session(current: dict, sid: str) -> list[dict]:
    """Leaving a conversation out (20.5): drops its results from the set, with `asked`, `last_asked` and
    `sessions_played` corrected. Returns what it removed ({target, entry}), kept so a put-back is exact."""
    removed = []
    for item in current.get("items") or []:
        mine = [r for r in item.get("results") or [] if r.get("session_id") == sid]
        if not mine:
            continue
        item["results"] = [r for r in item["results"] if r.get("session_id") != sid]
        item["asked"] = max(0, item.get("asked", 0) - len(mine))
        item["last_asked"] = _last_asked(item)
        removed += [{"target": item["target"], "entry": r} for r in mine]
    if removed:
        current["sessions_played"] = max(0, current.get("sessions_played", 0) - 1)
    return removed


def restore_session(current: dict, removed: list[dict]) -> bool:
    """Puts back what remove_session took (20.5), once: an entry already there is not added again."""
    by_target = {_norm(i["target"]): i for i in current.get("items") or []}
    added = False
    for r in removed:
        item = by_target.get(_norm(r["target"]))
        if item is None or r["entry"] in (item.get("results") or []):
            continue  # a newer set, or already back
        item["results"] = sorted([*item.get("results", []), r["entry"]], key=lambda e: e.get("date") or "")
        item["asked"] = item.get("asked", 0) + 1
        item["last_asked"] = _last_asked(item)
        added = True
    if added:
        current["sessions_played"] = current.get("sessions_played", 0) + 1
    return added
