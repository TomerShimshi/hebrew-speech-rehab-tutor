"""12: names he finds on his own, and the names game's stable check-in set."""

import datetime as dt

import pytest

from app import check_in_set, llm, word_bank
from app.agent.memory_tools import MemoryDraft, build_memory_tools
from app.agent.memory_update import run_memory_update
from app.agent.next_class import build_next_plan
from app.config import Settings
from app.schemas import CheckInItem, CheckInProposal, MemorySections, WordResult, WordSource, WordStats
from app.store import InMemorySessionStore
from app.transcripts import EndReason, TurnIn
from conftest import DAD
from fake_llm import FakeClient, text, tool_calls
from plan_helpers import a_plan, builder_rounds, plan_context, practice

TODAY = dt.date(2026, 10, 10)
SETTINGS = Settings(summary_model="primary", summary_fallback_models="fallback")


def gen(client, models, contents, config=None):
    return llm.generate(client, models, contents, config, sleep=lambda s: None)


def a_set(*items, created=TODAY, played=0):
    s = check_in_set.new_set([CheckInItem(target=t, question=f"q {t}", kind=k) for t, k in items], "sid00000", created)
    s["sessions_played"] = played
    return s


# ---- the word bank: where a name came from, and its schedule ----------------------------------------

def test_names_found_on_his_own_are_scheduled_like_successes_missed_ones_come_first():
    found = word_bank.record(None, WordResult.self_found, TODAY, source=WordSource.self_found)
    assert (found.source, found.self_found, found.next_due) == (WordSource.self_found, 1, "2026-10-11")
    missed = word_bank.record(None, WordResult.not_found, TODAY, source=WordSource.not_found)
    assert missed.next_due == TODAY.isoformat()
    practiced = word_bank.record(None, WordResult.failed, TODAY)
    bank = {"נמל": practiced, "עין גדי": found, "עין גב": missed}
    assert word_bank.due_words(bank, TODAY) == ["עין גב", "נמל"]  # couldn't find on his own -> first


def test_a_misheard_name_found_on_his_own_doesnt_move_the_schedule():
    s = word_bank.record(None, WordResult.self_found, TODAY, low_confidence=True, source=WordSource.self_found)
    assert (s.self_found, s.low_confidence, s.next_due) == (1, 1, None)


def test_only_practice_makes_a_name_treated_and_untreated_game_names_are_never_scheduled():
    probed = word_bank.record(None, WordResult.failed, TODAY, source=WordSource.probe)
    assert probed.next_due is None and not word_bank.is_treated(probed)
    found = word_bank.record(None, WordResult.self_found, TODAY, source=WordSource.self_found)
    assert not word_bank.is_treated(found)
    assert word_bank.is_treated(word_bank.record(found, WordResult.cued, TODAY))  # practiced now: wins
    assert word_bank.is_treated(WordStats(attempts=1))  # entries from before 12 count as practiced


# ---- the memory agent's tools -------------------------------------------------------------------

def draft_and_tools(probe_kinds=None):
    draft = MemoryDraft(sections=MemorySections(), word_bank={}, today=TODAY, probe_kinds=probe_kinds or {})
    return draft, {t.name: t.handler for t in build_memory_tools(draft)}


def test_free_talk_names_are_recorded_separately_with_their_source():
    draft, tools = draft_and_tools()
    tools["record_word_result"]({"word": "עין גדי", "result": "self_found", "asr_confidence": "high"})
    tools["record_word_result"]({"word": "עין גב", "result": "not_found", "asr_confidence": "low"})
    assert draft.own_names == [{"word": "עין גדי", "result": "self_found", "low_confidence": False},
                               {"word": "עין גב", "result": "not_found", "low_confidence": True}]
    assert draft.word_bank["עין גדי"].source is WordSource.self_found
    assert draft.probe_results == []
    with pytest.raises(ValueError, match="never for names-game items"):
        tools["record_word_result"]({"word": "עכו", "result": "self_found", "asr_confidence": "high", "probe": True})


def test_names_game_answers_keep_untreated_names_untrained():
    draft, tools = draft_and_tools({"עכו": "untreated", "טבריה": "treated"})
    tools["record_word_result"]({"word": "עכו", "result": "failed", "asr_confidence": "high", "probe": True})
    tools["record_word_result"]({"word": "טבריה", "result": "uncued", "asr_confidence": "high", "probe": True})
    assert draft.word_bank["עכו"].source is WordSource.probe and draft.word_bank["עכו"].next_due is None
    assert draft.word_bank["טבריה"].source is WordSource.practiced
    assert [r["kind"] for r in draft.probe_results] == ["untreated", "treated"]
    tools["record_names_game"]({"status": "played", "note": "Two names, one found."})
    assert draft.names_game == {"status": "played", "note": "Two names, one found."}
    with pytest.raises(ValueError):
        tools["record_names_game"]({"status": "maybe"})


def test_an_early_goodbye_is_a_tutor_issue():
    draft, tools = draft_and_tools()
    tools["report_tutor_issue"]({"kind": "early_goodbye", "tutor_said": "נהניתי מאוד לשמוע",
                                 "what_went_wrong": "She started the closing at 3 minutes."})
    assert draft.flags[0].issue == "early_goodbye"


# ---- the set: rotation and lifetime -----------------------------------------------------------------

def test_rotation_asks_the_least_recently_asked_names_and_mixes_the_kinds():
    current = a_set(("א", "treated"), ("ב", "treated"), ("ג", "treated"), ("ד", "untreated"), ("ה", "untreated"))
    first = [c["target"] for c in check_in_set.choose_items(current)]
    assert first == ["א", "ב", "ד"]  # three treated would be first in line: one untreated swapped in
    check_in_set.record_results(current, [{"word": w, "result": "uncued"} for w in first], "s1", TODAY)
    assert [c["target"] for c in check_in_set.choose_items(current)] == ["ג", "ה", "א"]
    assert current["sessions_played"] == 1
    # a skipped game records nothing, so the same names come up again
    assert not check_in_set.record_results(current, [], "s2", TODAY)
    assert [c["target"] for c in check_in_set.choose_items(current)] == ["ג", "ה", "א"]


@pytest.mark.names_game_set
def test_a_set_lasts_about_three_weeks_or_ten_sessions():
    assert check_in_set.needs_new_set(None, TODAY)
    assert not check_in_set.needs_new_set(a_set(("א", "treated")), TODAY + dt.timedelta(days=20))
    assert check_in_set.needs_new_set(a_set(("א", "treated")), TODAY + dt.timedelta(days=21))
    assert check_in_set.needs_new_set(a_set(("א", "treated"), played=10), TODAY)


def test_retiring_keeps_the_old_set_for_comparison_and_forgetting_memory_retires_it():
    store = InMemorySessionStore()
    store.save_check_in_set(DAD, a_set(("א", "treated")))
    store.forget_memory(DAD)
    assert store.get_check_in_set(DAD) is None
    assert [s["items"][0]["target"] for s in store.list_check_in_history(DAD)] == ["א"]


# ---- the plan builder proposes a set when one is due --------------------------------------------------

MEMORY = {"memory_prompt": "He lives in נהריה; he loves גן השלושה.",
          "sections": {"personal_facts": ["Lives in נהריה", "His favourite park is גן השלושה"]},
          "word_bank": {"מצפה רמון": {"attempts": 2, "failed": 1, "cued": 1, "last_result": "cued"},
                        "עין גדי": {"attempts": 1, "self_found": 1, "source": "self_found"}}}


def proposal(*names):
    return CheckInProposal(items=[CheckInItem(target=n, question=f"q {n}", about_his_life=n == "גן השלושה")
                                  for n in names], rationale="Half practiced, half new.")


@pytest.mark.names_game_set
def test_builder_proposes_a_set_first_and_keeps_its_untreated_names_out_of_practice():
    store = InMemorySessionStore()
    store.save_memory(DAD, "s0", MEMORY, None)
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    # the builder tries two untreated set names: rejected on the spot; נמל יפו is fine
    client = FakeClient(text("{}", parsed=proposal("מצפה רמון", "גן השלושה", "עין גדי", "כרמיאל", "ירושלים",
                                                   "קריית שמונה", "דני")),
                        *builder_rounds(names=("כרמיאל", "עין גדי", "נמל יפו", "טבריה")))
    assert build_next_plan(store, client, SETTINGS, DAD, sid, today=TODAY, generate_fn=gen) == "done"
    current = store.get_check_in_set(DAD)
    assert [(i["target"], i["kind"]) for i in current["items"]] == [
        ("מצפה רמון", "treated"), ("גן השלושה", "untreated"), ("עין גדי", "untreated"),
        ("כרמיאל", "untreated"), ("קריית שמונה", "untreated"), ("דני", "untreated")]  # ירושלים: too famous
    assert current["rationale"] == "Half practiced, half new."
    context = plan_context(client)
    assert "NAMES GAME SET" in context and "כרמיאל (untreated)" in context
    # כרמיאל and עין גדי are untreated set names: never practiced
    practiced = [s["name"] for s in store.get_next_plan(DAD)["steps"] if s["kind"] == "practice"]
    assert practiced == ["נמל יפו", "טבריה"]


@pytest.mark.names_game_set
def test_a_failed_set_proposal_never_fails_the_plan():
    store = InMemorySessionStore()
    store.save_memory(DAD, "s0", MEMORY, None)
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    thin = proposal("ירושלים", "תל אביב")
    client = FakeClient(text("{}", parsed=thin), text("{}", parsed=thin), *builder_rounds())
    assert build_next_plan(store, client, SETTINGS, DAD, sid, today=TODAY, generate_fn=gen) == "done"
    assert store.get_check_in_set(DAD) is None  # no game until the next build manages one


# ---- the memory update feeds the set ----------------------------------------------------------------

def test_memory_update_records_the_game_in_the_set_and_own_names_on_the_session():
    store = InMemorySessionStore()
    store.save_check_in_set(DAD, a_set(("עכו", "untreated"), ("טבריה", "treated")))
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    store.update_session(DAD, sid, {"class_plan": a_plan(steps=[{"kind": "opening"}, {"kind": "names_game", "items": [
        {"target": "עכו", "kind": "untreated", "elicit": "q עכו"},
        {"target": "טבריה", "kind": "treated", "elicit": "q טבריה"}]}]).model_dump(mode="json")})
    store.upsert_turns(DAD, sid, [TurnIn(seq=i, speaker=sp, text=tx, t_start_s=i * 10) for i, (sp, tx) in enumerate([
        ("tutor", "q עכו"), ("patient", "לא יודע"), ("tutor", "q טבריה"), ("patient", "טבריה"),
        ("patient", "היינו נוסעים למעיינות... איך קוראים לזה... עין גדי")])])
    store.end_session(DAD, sid, EndReason.tutor_goodbye)
    client = FakeClient(
        tool_calls(("record_word_result", {"word": "עכו", "result": "failed", "asr_confidence": "high", "probe": True}),
                   ("record_word_result", {"word": "טבריה", "result": "uncued", "asr_confidence": "high", "probe": True}),
                   ("record_word_result", {"word": "עין גדי", "result": "self_found", "asr_confidence": "high"}),
                   ("record_names_game", {"status": "played", "note": "Asked both."})),
        text("done"),
    )
    assert run_memory_update(store, client, SETTINGS, DAD, sid, today=TODAY, generate_fn=gen) == "done"
    session = store.get_session(DAD, sid)
    assert session["own_names"] == [{"word": "עין גדי", "result": "self_found", "low_confidence": False}]
    assert session["names_game"]["status"] == "played"
    current = store.get_check_in_set(DAD)
    assert current["sessions_played"] == 1
    assert {i["target"]: [r["result"] for r in i["results"]] for i in current["items"]} == {
        "עכו": ["failed"], "טבריה": ["uncued"]}
    bank = store.get_memory(DAD)["word_bank"]
    assert (bank["עכו"]["source"], bank["עין גדי"]["source"]) == ("probe", "self_found")


# ---- 12b: a reserve, the plan sized to his pace, today's names in the transcription ---------------

def test_his_pace_is_measured_from_his_real_sessions():
    from app.agent.next_class import render_pace, speaking_pace
    store = InMemorySessionStore()
    start = dt.datetime(2026, 10, 11, 7, 0, tzinfo=dt.timezone.utc)
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    turns = [TurnIn(seq=i, speaker="patient" if i % 2 else "tutor", text="מילה אחת שתיים", t_start_s=i * 10)
             for i in range(40)]
    store.upsert_turns(DAD, sid, turns)
    store.end_session(DAD, sid, EndReason.tutor_goodbye)
    store.update_session(DAD, sid, {"started_at": start, "ended_at": start + dt.timedelta(minutes=5)})
    short = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")  # too short to count
    store.end_session(DAD, short, EndReason.end_button)
    rows = speaking_pace(store, DAD)
    assert rows == [{"date": "2026-10-11", "minutes": 5.0, "answers_per_min": 4.0, "words_per_answer": 3.0}]
    assert "Overall: 4.0 answers per minute -> FAST pace." in render_pace(rows)
    assert "typical" in render_pace([])


def test_todays_names_never_go_into_the_transcription_vocabulary(env):  # 30.10: they came out instead of his words
    from conftest import FakeAuthTokens, auth
    env.store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee."}, None)
    env.store.save_next_plan(DAD, "s0", a_plan(steps=[
        {"kind": "opening"}, {"kind": "names_game"}, {"kind": "practice", **practice("כרמיאל")},
        {"kind": "practice", **practice("נהריה")}]).model_dump(mode="json"))
    env.store.save_check_in_set(DAD, a_set(("עכו", "untreated")))
    env.client.post("/api/session/start", headers=auth())
    assert FakeAuthTokens.last_config.live_connect_constraints.config.input_audio_transcription.custom_vocabulary is None


def test_the_tutor_is_told_no_wrap_up_questions():
    from app.prompts import render_tutor_prompt
    text = " ".join(render_tutor_prompt().text.split())
    assert "no wrap-up questions" in text and "end a TOPIC, not the session" in text


def test_the_names_game_asks_once_more_when_his_answer_is_unclear():
    from app.steps import NamesGameStep
    rules = NamesGameStep.RULES
    assert "סליחה, לא שמעתי טוב, תגיד שוב?" in rules
    assert "no second try" not in rules.lower()


def test_the_names_game_counts_an_answer_that_sounds_like_the_name():
    from app.steps import NamesGameStep
    assert "sounds like" in NamesGameStep.RULES.lower()
