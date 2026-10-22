"""Adjusting to his progress, like a therapist (sub-plan 17): plain code, no LLM.

Per practiced area, a series of code-scored results (oldest -> newest; never an attempt marked
low-confidence), and explicit rules -- never from one session:
  mastered  ~80% on 3 results in a row (for naming: untreated names too) -> the next level, less time
  worse     the last 2 clearly below the 3 before them                    -> a level down, more time
  stalled   no gain over the last 3 results (and not mastered)           -> change the approach
After a decision, an area waits for 3 new results before the next one. Every decision is logged with its
reason; worse and stalled also become points for his therapist. The family can lock an area (never
changed) or undo a decision (back to its previous setting). The thresholds are ours (no agreed standard
exists): constants here, to tune after watching them work.
"""

import datetime as dt

MASTERED_PCT = 80
MASTERED_RUN = 3
WORSE_DROP = 20
WINDOW = 3
MIN_LEVEL, MAX_LEVEL, START_LEVEL = 1, 5, 2
SHARES = ("less", "normal", "more")

AREAS = {
    "naming": "Naming (proper names: the names game)",
    "connected_speech": "Connected speech (the story to retell)",
    "summarizing": "Summarizing a short text",
    "sequencing": "Telling things in order",
}
# What a level means to the plan builder, per area.
LEVEL_GUIDE = {
    "naming": {1: "familiar names from his own life, with a hint early", 2: "names from his life and well-known places",
               3: "less frequent names; hints only after a real try", 4: "rarer names (people, places, brands); "
               "a hint only if he asks", 5: "rare names, in longer conversation, no hints"},
}


def _pct_share(results: list[dict], kind: str | None = None) -> int | None:
    got = [r for r in results if not r.get("low_confidence") and (kind is None or r.get("kind") == kind)]
    if not got:
        return None
    return round(100 * sum(1 for r in got if r.get("result") == "uncued") / len(got))


def series(sessions: list[dict]) -> dict[str, list[dict]]:
    """Per area, its results oldest -> newest: {value, untreated (naming), session, date}."""
    out: dict[str, list[dict]] = {a: [] for a in AREAS}
    for s in reversed(sessions):  # the store lists newest first
        if s.get("status") != "ended":
            continue
        base = {"session": s.get("id"), "date": str(s.get("started_at") or "")[:10]}
        probe = s.get("probe_results") or []
        value = _pct_share(probe)
        if value is not None:
            out["naming"].append({**base, "value": value, "untreated": _pct_share(probe, "untreated")})
        for area, field, key in (("connected_speech", "story_probe", "ideas_pct"), ("summarizing", "summarizing", "ideas_pct"),
                                 ("sequencing", "sequencing", "order_pct")):
            r = s.get(field) or {}
            if r.get("status") == "done" and not r.get("low_confidence") and r.get(key) is not None:
                out[area].append({**base, "value": r[key]})
    return out


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def decide(area: str, points: list[dict], setting: dict) -> dict | None:
    """The rule that fires for this area now, or None. `setting`: its current {level, share, lock, seen}."""
    if setting.get("lock"):
        return None
    fresh = len(points) - int(setting.get("seen", 0))  # results since the last decision
    if fresh < WINDOW:
        return None
    last = points[-WINDOW:]
    values = [p["value"] for p in last]
    level = int(setting.get("level", START_LEVEL))
    untreated_ok = area != "naming" or all((p.get("untreated") is None) or p["untreated"] >= MASTERED_PCT for p in last)
    if all(v >= MASTERED_PCT for v in values) and untreated_ok:
        return {"rule": "mastered", "level": min(MAX_LEVEL, level + 1), "share": "less",
                "reason": f"{values} -- {MASTERED_RUN} results in a row at {MASTERED_PCT}%+"}
    # Worse and stalled compare with the 3 results before the window -- never with fewer (a dry run on
    # real data, 21.10: one earlier result made two ordinary results look like a decline).
    before = [p["value"] for p in points[-(2 * WINDOW):-WINDOW]]
    if len(before) < WINDOW:
        return None
    if _mean([p["value"] for p in points[-2:]]) <= _mean(before) - WORSE_DROP:
        return {"rule": "worse", "level": max(MIN_LEVEL, level - 1), "share": "more",
                "reason": f"the last two {[p['value'] for p in points[-2:]]} vs before {before}"}
    # Stalled only below mastery: no gain at the top of the scale is not a problem (21.10).
    if _mean(values) < MASTERED_PCT and _mean(values) <= _mean(before):
        return {"rule": "stalled", "level": level, "share": setting.get("share", "normal"), "change_approach": True,
                "reason": f"no gain: {values} after {before}"}
    return None


THERAPIST_POINT = {
    "worse": "נראה שיש ירידה ב{area} בשיחות האחרונות -- כדאי לבדוק עם הקלינאית",
    "stalled": "אין התקדמות ב{area} בכמה שיחות -- כדאי לשאול את הקלינאית אם לשנות גישה",
    "mastered": "נראה ש{area} השתפר מאוד -- כדאי לשאול את הקלינאית אם להעביר את המיקוד",
}
AREA_HE = {"naming": "שליפת שמות", "connected_speech": "דיבור רציף", "summarizing": "סיכום במילים שלו",
           "sequencing": "סיפור לפי סדר"}


def update(doc: dict | None, sessions: list[dict], today: dt.date) -> tuple[dict, list[dict]]:
    """Applies the rules to his results. Returns the updated progress doc {areas, log} and the new
    decisions (each also a point for his therapist when it's worth raising)."""
    doc = {"areas": dict((doc or {}).get("areas") or {}), "log": list((doc or {}).get("log") or [])}
    new = []
    for area, points in series(sessions).items():
        setting = {"level": START_LEVEL, "share": "normal", "seen": 0, **(doc["areas"].get(area) or {})}
        d = decide(area, points, setting)
        if d:
            entry = {"date": today.isoformat(), "area": area, "rule": d["rule"], "reason": d["reason"],
                     "from": {"level": setting["level"], "share": setting["share"]},
                     "to": {"level": d["level"], "share": d["share"]}, "by": "app"}
            setting = {**setting, "level": d["level"], "share": d["share"], "seen": len(points),
                       "change_approach": bool(d.get("change_approach")), "last": entry}
            doc["log"].append(entry)
            new.append({**entry, "point": THERAPIST_POINT[d["rule"]].format(area=AREA_HE[area])})
        doc["areas"][area] = setting
    doc["log"] = doc["log"][-60:]
    return doc, new


def undo(doc: dict, area: str, by: str, today: dt.date) -> dict:
    """Back to the setting before the area's last decision (logged)."""
    setting = dict((doc.get("areas") or {}).get(area) or {})
    last = setting.get("last")
    if not last:
        raise ValueError("no decision to undo")
    setting.update(level=last["from"]["level"], share=last["from"]["share"], change_approach=False, last=None)
    doc = {**doc, "areas": {**doc.get("areas", {}), area: setting}}
    doc["log"] = [*doc.get("log", []), {"date": today.isoformat(), "area": area, "rule": "undo", "by": by,
                                        "reason": f"undid '{last['rule']}' of {last['date']}"}]
    return doc


def set_lock(doc: dict, area: str, lock: bool, by: str, today: dt.date) -> dict:
    setting = {"level": START_LEVEL, "share": "normal", "seen": 0, **((doc.get("areas") or {}).get(area) or {})}
    setting["lock"] = lock
    doc = {**doc, "areas": {**(doc.get("areas") or {}), area: setting}}
    doc["log"] = [*(doc.get("log") or []), {"date": today.isoformat(), "area": area, "rule": "lock" if lock else "unlock",
                                            "by": by, "reason": "the family"}]
    return doc


def render(doc: dict | None, points: dict[str, list[dict]]) -> str:
    """HIS PROGRESS for the plan builder: per area, the recent results, the setting, the last decision."""
    lines = []
    areas = (doc or {}).get("areas") or {}
    for area, name in AREAS.items():
        pts = points.get(area) or []
        if not pts and area not in areas:
            continue
        st = {"level": START_LEVEL, "share": "normal", **(areas.get(area) or {})}
        recent = ", ".join(f"{p['value']}%" + (f" (untreated {p['untreated']}%)" if p.get("untreated") is not None else "")
                           for p in pts[-5:]) or "no results yet"
        guide = LEVEL_GUIDE.get(area, {}).get(int(st["level"]), "")
        line = f"- {name}: recent {recent}. Level {st['level']}/5{f' ({guide})' if guide else ''}; time: {st['share']}"
        if st.get("lock"):
            line += "; LOCKED by the family"
        if st.get("change_approach"):
            line += "; NO GAIN lately -- try another kind of task or cue for it"
        if st.get("last"):
            line += f"; last change {st['last']['date']}: {st['last']['rule']} ({st['last']['reason']})"
        lines.append(line)
    return "\n".join(lines)
