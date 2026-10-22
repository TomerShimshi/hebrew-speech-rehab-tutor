"""17: measuring like a therapist (probes) and adjusting to it (rules, a log, the family's veto)."""
import datetime as dt

from app import probes, progress
from app.store import InMemorySessionStore
from conftest import DAD, TOMER, auth

TODAY = dt.date(2026, 10, 21)


def sessions(field, values, **extra):
    """Ended regular sessions with one result each, oldest first in `values`; returned newest first."""
    out = []
    for i, v in enumerate(values):
        r = {"status": "done", "ideas_pct": v, **extra} if field != "probe_results" else v
        out.append({"id": f"s{i}", "status": "ended", "started_at": dt.datetime(2026, 10, 1 + i),
                    "class_plan": {"plan_type": "regular"}, field: r})
    return out[::-1]


# ---- the rules ----------------------------------------------------------------------------------

def test_mastered_raises_the_level_and_gives_less_time():
    doc, new = progress.update(None, sessions("story_probe", [60, 70, 85, 90, 95]), TODAY)
    st = doc["areas"]["connected_speech"]
    assert [n["rule"] for n in new] == ["mastered"] and (st["level"], st["share"]) == (3, "less")
    assert "השתפר" in new[0]["point"] and doc["log"][-1]["reason"].startswith("[85, 90, 95]")


def test_stalled_and_worse():
    assert [n["rule"] for n in progress.update(None, sessions("story_probe", [70, 72, 70, 60, 65, 62]), TODAY)[1]] == ["stalled"]
    doc, new = progress.update(None, sessions("story_probe", [80, 80, 80, 80, 50, 45]), TODAY)
    assert [n["rule"] for n in new] == ["worse"] and doc["areas"]["connected_speech"]["share"] == "more"


def test_never_from_one_session_or_a_doubtful_transcription():
    assert progress.update(None, sessions("story_probe", [90, 95]), TODAY)[1] == []  # too few
    doubtful = sessions("story_probe", [90, 95, 99], low_confidence=True)
    assert progress.series(doubtful)["connected_speech"] == []  # never counted


def test_naming_mastery_needs_the_untreated_names_too():
    def game(untreated_ok):
        return [{"word": "א", "result": "uncued", "kind": "treated"},
                {"word": "ב", "result": "uncued" if untreated_ok else "failed", "kind": "untreated"}]
    # overall 50% when untreated fail -> not mastered; all uncued -> mastered
    assert progress.update(None, sessions("probe_results", [game(True)] * 3), TODAY)[1][0]["rule"] == "mastered"
    assert all(n["rule"] != "mastered" for n in progress.update(None, sessions("probe_results", [game(False)] * 3), TODAY)[1])


def test_after_a_decision_it_waits_for_three_new_results():
    doc, _ = progress.update(None, sessions("story_probe", [85, 90, 95]), TODAY)
    assert progress.update(doc, sessions("story_probe", [85, 90, 95, 96]), TODAY)[1] == []


def test_the_family_locks_and_undoes():
    doc, _ = progress.update(None, sessions("story_probe", [85, 90, 95]), TODAY)
    undone = progress.undo(doc, "connected_speech", TOMER, TODAY)
    assert undone["areas"]["connected_speech"]["level"] == progress.START_LEVEL and undone["log"][-1]["rule"] == "undo"
    locked = progress.set_lock({}, "connected_speech", True, TOMER, TODAY)
    assert progress.update(locked, sessions("story_probe", [85, 90, 95]), TODAY)[1] == []  # never changed
    text = progress.render(locked, progress.series(sessions("story_probe", [85, 90, 95])))
    assert "LOCKED by the family" in text and "85%, 90%, 95%" in text


# ---- the probes ----------------------------------------------------------------------------------

def test_the_story_probe_every_other_session_in_a_fixed_rotation():
    regular = lambda probe: {"status": "ended", "class_plan": {"plan_type": "regular"},  # noqa: E731
                             "story_probe": probe, "started_at": dt.datetime(2026, 10, 1)}
    assert probes.story_due([]) is None  # no regular session yet
    assert probes.story_due([regular(None)])["id"] == probes.stories()[0]["id"]
    assert probes.story_due([regular({"status": "done"}), regular(None)]) is None  # just had one
    two_done = [regular(None), regular({"status": "done"}), regular({"status": "done"})]
    assert probes.story_due(two_done)["id"] == probes.stories()[1]["id"]  # each story told twice, then the next
    talk = probes.talk_measures([{"speaker": "patient", "text": "אחת שתיים שלוש"}, {"speaker": "tutor", "text": "x"},
                                 {"speaker": "patient", "text": " ".join(["מילה"] * 13)}])
    assert talk == {"answers": 2, "avg_words": 8.0, "long_answers": 1}


def test_his_view_every_two_weeks():
    def regular(day, view=None):
        return {"status": "ended", "class_plan": {"plan_type": "regular"}, "started_at": dt.datetime(2026, 10, day),
                "his_view": view}
    assert probes.view_due([], TODAY) is False
    assert probes.view_due([regular(20)], TODAY) is True  # never asked
    assert probes.view_due([regular(15, {"status": "done", "score": 4})], TODAY) is False  # 6 days ago
    assert probes.view_due([regular(1, {"status": "done", "score": 4})], TODAY) is True


# ---- the caregiver page --------------------------------------------------------------------------

def test_the_caregiver_page_locks_undoes_and_keeps_the_therapists_scores(env):
    env.store.save_progress(DAD, progress.update(None, sessions("story_probe", [85, 90, 95]), TODAY)[0])
    assert env.client.post(f"/api/caregiver/{DAD}/progress/connected_speech/undo", headers=auth("tok-tomer")).status_code == 200
    assert env.client.post(f"/api/caregiver/{DAD}/progress/connected_speech/undo", headers=auth("tok-tomer")).status_code == 409
    assert env.client.post(f"/api/caregiver/{DAD}/progress/naming/lock", headers=auth("tok-tomer"),
                           json={"lock": True}).status_code == 200
    assert env.client.post(f"/api/caregiver/{DAD}/therapist-scores", headers=auth("tok-tomer"),
                           json={"date": "2026-11-01", "test": "WAB-R AQ", "score": "92"}).status_code == 200
    ov = env.client.get(f"/api/caregiver/{DAD}/overview", headers=auth("tok-tomer")).json()["progress"]
    assert ov["areas"]["naming"]["lock"] is True and ov["therapist_scores"][0]["score"] == "92"
    assert env.client.post(f"/api/caregiver/{DAD}/progress/naming/lock", headers=auth(), json={"lock": False}).status_code == 403


def test_no_stall_at_the_top_and_no_verdict_from_too_little_history():
    assert progress.update(None, sessions("story_probe", [100, 100, 100, 100, 100, 67]), TODAY)[1] == []
    assert progress.update(None, sessions("story_probe", [100, 67, 67]), TODAY)[1] == []  # one result before: no verdict


def test_the_builder_gets_his_progress_and_the_naming_dose_is_checked():
    import pytest
    from app.agent.plan_tools import PlanDraft, build_plan_tools
    from app.agent.next_class import build_context
    context = build_context({"memory_prompt": "m"}, [], "", TODAY, progress_text="- Naming: recent 67%. Level 2/5")
    assert "# HIS PROGRESS" in context and "Level 2/5" in context
    draft = PlanDraft()
    tools = {t.name: t.handler for t in build_plan_tools(draft, check_practice=lambda s: None, his_games=set(),
                                                         set_names=set(), naming_share="more")}
    tools["set_goal"]({"type": "name_retrieval", "description": "Names."})
    for i in range(10):
        tools["add_thread"]({"topic": f"t{i}", "question": "?"})
    with pytest.raises(ValueError, match="at least 2 practice steps"):
        tools["finish"]({})


def test_the_story_bank_is_even():
    """Equal difficulty is what makes the scores comparable (17): every story is checked here."""
    bank = probes.stories()
    assert len(bank) >= 30 and len({s["id"] for s in bank}) == len(bank)
    for s in bank:
        assert len(s["main_ideas"]) == 5, s["id"]
        assert 28 <= len(s["story"].split()) <= 55, s["id"]  # ~30-50 words: comparable effort
    assert [s["id"] for s in bank[:2]] == ["lost_keys", "rain_wedding"]  # the rotation already under way is kept


def test_the_story_step_acknowledges_the_retelling_before_moving_on():
    from app.steps import StoryProbeStep
    step = StoryProbeStep(story_id="lost_keys", title="the lost keys", story="סיפור.", main_ideas=["a"])
    assert step.answers_needed() == 2  # the retelling, then one exchange about it (21.10)
    rules = " ".join(step.instruction().split())
    assert "react to the STORY itself" in rules and "never count or grade" in rules
