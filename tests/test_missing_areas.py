"""17.5: the missing areas (repetition, understanding, clarity) -- confirmed before practiced, then 17's
progress rules from level 1, at most one step a session, measured on fixed banks."""
import datetime as dt

import pytest

from app import missing_areas, progress
from app.agent.memory_tools import MemoryDraft, build_memory_tools
from app.agent.next_class import apply_missing_areas
from app.agent.plan_tools import PlanDraft, build_plan_tools
from app.schemas import MemorySections
from app.store import InMemorySessionStore
from conftest import DAD, TOMER, auth

TODAY = dt.date(2026, 10, 22)
NEW = "new@example.com"


def area(*levels, **extra):
    return {"level": levels[-1] if levels else "ok", "history": [{"level": lv} for lv in levels], **extra}


# ---- confirming first --------------------------------------------------------------------------------

def test_seen_once_rechecking_then_confirmed_or_not():
    assert missing_areas.status(area("ok", "ok")) == "fine"
    assert missing_areas.status(area("some_difficulty")) == "seen_once"
    assert missing_areas.status(area("some_difficulty", "ok")) == "rechecking"
    assert missing_areas.status(area("some_difficulty", "ok", "clear_difficulty")) == "confirmed"
    assert missing_areas.status(area("some_difficulty", "ok", "ok")) == "not_confirmed"
    assert missing_areas.status(area("some_difficulty", "ok", "ok", "some_difficulty")) == "seen_once"  # a new window
    assert missing_areas.status(area("some_difficulty", family_status="not_confirmed")) == "not_confirmed"  # family wins
    assert missing_areas.status(area("ok", family_status="confirmed")) == "confirmed"


def test_a_new_account_gets_a_recheck_and_a_confirmed_area_starts_small():
    store = InMemorySessionStore()
    store.save_needs(NEW, {"areas": {"repetition": area("some_difficulty")}})
    apply_missing_areas(store, NEW, TODAY)
    needs = store.get_needs(NEW)
    assert needs["areas"]["repetition"]["status"] == "seen_once"
    assert [c["area"] for c in needs["pending_checks"]] == ["repetition"]  # one re-check queued, from the bank
    apply_missing_areas(store, NEW, TODAY)
    assert len(store.get_needs(NEW)["pending_checks"]) == 1  # not twice
    store.save_needs(NEW, {**store.get_needs(NEW), "areas": {"repetition": area("some_difficulty", "some_difficulty")}})
    apply_missing_areas(store, NEW, TODAY)
    st = store.get_progress(NEW)["areas"]["repetition"]
    assert (st["active"], st["level"], st["share"]) == (True, 1, "less")
    assert store.get_progress(NEW)["log"][-1]["rule"] == "confirmed"
    assert any("מתחילה לתרגל" in p["text"] for p in store.get_needs(NEW)["therapist_points"])  # the family is told


def test_an_uploaded_profile_gets_no_recheck_items():
    store = InMemorySessionStore()
    store.save_profile(DAD, "his assessment", "uploaded", TOMER)
    store.save_needs(DAD, {"areas": {"clarity": area("some_difficulty")}})
    apply_missing_areas(store, DAD, TODAY)
    assert not store.get_needs(DAD).get("pending_checks")  # no new checks in his sessions (17)


def test_unconfirmed_areas_never_reach_the_progress_rules():
    sessions = [{"id": "s1", "status": "ended", "started_at": dt.datetime(2026, 10, 1 + i),
                 "area_probe": {"area": "clarity", "status": "done", "pct": 90}} for i in range(4)][::-1]
    doc, new = progress.update(None, sessions, TODAY)
    assert "clarity" not in doc["areas"] and new == []
    active = missing_areas.hand_over({}, "clarity", TODAY.isoformat())
    doc, new = progress.update(active, sessions, TODAY)
    assert [n["rule"] for n in new] == ["mastered"] and doc["areas"]["clarity"]["level"] == 2


# ---- one step a session, at its dose ----------------------------------------------------------------

def regular(kinds=(), probe=None, day=1):
    return {"status": "ended", "started_at": dt.datetime(2026, 10, day), "area_probe": probe,
            "class_plan": {"plan_type": "regular", "steps": [{"kind": k} for k in kinds]}}


def test_practice_turn_one_area_by_its_dose():
    doc = missing_areas.hand_over(missing_areas.hand_over({}, "repetition", "d"), "clarity", "d")
    assert missing_areas.practice_turn(None, []) is None
    assert missing_areas.practice_turn(doc, [regular()]) in ("repetition", "clarity")
    just_rep = [regular(["repetition"], day=2), regular(["clarity"], day=1)]
    assert missing_areas.practice_turn(doc, just_rep) == "clarity"  # less time: every other session
    doc["areas"]["repetition"]["share"] = "normal"
    assert missing_areas.practice_turn(doc, [regular(["repetition"], day=2), regular(["clarity"], day=1)]) == "clarity"


def test_the_builder_must_add_the_areas_step_and_only_one():
    draft = PlanDraft()
    tools = {t.name: t.handler for t in build_plan_tools(draft, check_practice=lambda s: None, his_games=set(),
                                                         set_names=set(), missing_area="repetition")}
    assert "add_understanding" not in tools
    tools["set_goal"]({"type": "conversation", "description": "Talk."})
    for i in range(10):
        tools["add_thread"]({"topic": f"t{i}", "question": "?"})
    with pytest.raises(ValueError, match="add_repetition"):
        tools["finish"]({})
    tools["add_repetition"]({"items": ["כוס קפה", "פתח את הדלת", "הכלב רץ בחצר"]})
    with pytest.raises(ValueError, match="one practice step"):
        tools["add_repetition"]({"items": ["א", "ב", "ג"]})


# ---- measured on the fixed banks ----------------------------------------------------------------------

def test_probes_use_the_same_mix_of_levels_and_never_with_the_story():
    for a in missing_areas.AREAS:
        assert len(missing_areas.bank(a)) >= 25
        mix = [[i["level"] for i in missing_areas.probe_items(a, k)] for k in range(3)]
        assert mix[0] == mix[1] == mix[2]  # comparable
        assert missing_areas.probe_items(a, 0) != missing_areas.probe_items(a, 1)  # but not the same items
    doc = missing_areas.hand_over({}, "understanding", "d")
    assert missing_areas.probe_due(doc, [])[0] == "understanding"  # the baseline, right after confirmation
    assert missing_areas.probe_due(doc, [regular(probe={"area": "understanding"})]) is None  # every ~3rd session


def test_scored_by_code_from_what_he_said():
    items = [{"text": "כוס קפה חם"}, {"text": "הכלב רץ בחצר"}]
    r = missing_areas.score("repetition", items, {"results": [{"item": 1, "said": "כוס קפה חם"},
                                                            {"item": 2, "said": "הכלב רץ"}]})
    assert (r["status"], r["pct"]) == ("done", 83)  # 3/3 and 2/3 words
    u = missing_areas.score("understanding", items, {"results": [{"item": 1, "correct": True}, {"item": 2, "correct": False}]})
    assert u["pct"] == 50
    assert missing_areas.score("clarity", items, None)["status"] == "not_reported"
    draft = MemoryDraft(sections=MemorySections(), word_bank={}, today=TODAY)
    tools = {t.name: t.handler for t in build_memory_tools(draft)}
    tools["record_area_probe"]({"results": [{"item": 1, "said": "כוס קפה", "correct": False}], "low_confidence": True})
    assert draft.area_probe["low_confidence"] is True and draft.area_probe["results"][0]["said"] == "כוס קפה"


def test_the_family_confirms_or_cancels(env):
    url = f"/api/caregiver/{DAD}/needs/clarity/status"
    assert env.client.put(url, headers=auth("tok-tomer"), json={"status": "not_confirmed"}).status_code == 200
    assert env.store.get_needs(DAD)["areas"]["clarity"]["family_status"] == "not_confirmed"
    assert env.client.put(url, headers=auth("tok-tomer"), json={"status": "maybe"}).status_code == 422
    assert env.client.put(f"/api/caregiver/{DAD}/needs/naming/status", headers=auth("tok-tomer"),
                          json={"status": "confirmed"}).status_code == 404  # only the missing areas
