"""8.5: the plan must never invent his people -- the case from Tomer's session on 6.10.26.
Since 12 the check-in is the names game's stable set; since 13.5 each practice step is checked
the moment the plan builder adds it, and the builder fixes it on the spot."""

import datetime as dt

from app import llm
from app.agent.memory_tools import MemoryDraft, build_memory_tools
from app.agent.next_class import build_next_plan, enforce_set_rules, grounding_text, practice_checker
from app.config import Settings
from app.schemas import CheckInProposal
from app.steps import PracticeStep
from app.store import InMemorySessionStore
from app.transcripts import EndReason, TurnIn
from fake_llm import FakeClient, text, tool_calls
from plan_helpers import build_calls, practice

PID = "tomer@example.com"
SETTINGS = Settings(summary_model="primary", summary_fallback_models="fallback")
MEMORY = {"memory_prompt": "He likes Nahariya beach (חוף נהריה) and lived in Ramat Gan (רמת גן).",
          "sections": {"personal_facts": ["Lived in רמת גן and enjoyed פארק הירקון"]},
          "word_bank": {"מצפה רמון": {"attempts": 1}}}


def item(target, question, about=False):
    return {"target": target, "question": question, "about_his_life": about}


def store_with_his_words(*lines):
    store = InMemorySessionStore()
    sid = store.create_session(PID, user_email=PID, model="m", prompt_version="v")
    store.upsert_turns(PID, sid, [TurnIn(seq=i, speaker="patient", text=t, t_start_s=i) for i, t in enumerate(lines)])
    store.end_session(PID, sid, EndReason.tutor_goodbye)
    store.save_memory(PID, sid, MEMORY, None)
    return store, sid


def gen(c, m, ct, cf=None):
    return llm.generate(c, m, ct, cf, sleep=lambda s: None)


def check(store, name, question, about=False, untreated=()):
    known = grounding_text(store, PID, MEMORY, "", "")
    return practice_checker(known, set(untreated))(PracticeStep(**practice(name, question=question, about=about)))


def test_invented_people_are_rejected_known_ones_accepted():
    store, _ = store_with_his_words("יש לי אישה קוראים לה שיר")
    assert "not in his data" in check(store, "דני", "איך קוראים לחבר שקרוב אליך במיוחד?")  # personal by wording
    assert "not in his data" in check(store, "רונית", "מי מארגנת את החגים במשפחה?", about=True)
    assert check(store, "שיר", "איך קוראים לאשתך?") is None                       # he said it himself
    assert check(store, "פארק הירקון", "באיזה פארק טיילת?", about=True) is None    # in the memory
    assert check(store, "עכו", "העיר העתיקה עם החומות בצפון") is None              # general knowledge
    assert "untreated names-game name" in check(store, "עכו", "x", untreated={"עכו"})


def test_the_names_game_set_follows_the_same_rule():
    store, _ = store_with_his_words("יש לי אישה קוראים לה שיר")
    known = grounding_text(store, PID, MEMORY, "", "")
    proposal = CheckInProposal(items=[
        item("דני", "איך קוראים לחבר הכי קרוב שלך?"),                        # invented
        item("שיר", "איך קוראת אשתך?", about=True),                           # he said it
        item("פארק הירקון", "הפארק שטיילת בו ברמת גן?", about=True),          # in the memory
        item("עכו", "העיר העתיקה עם החומות בצפון?"),
        item("ירושלים", "עיר הבירה?"),                                          # too famous as a new name
        item("מצפה רמון", "העיירה על שפת המכתש?"),                            # practiced: treated
    ])
    items = enforce_set_rules(proposal, {"מצפה רמון": a_practiced_word()}, known)
    assert [(i.target, i.kind) for i in items] == [("שיר", "untreated"), ("פארק הירקון", "untreated"),
                                                    ("עכו", "untreated"), ("מצפה רמון", "treated")]


def a_practiced_word():
    from app.schemas import WordStats
    return WordStats(attempts=1, cued=1)


def test_vowel_marks_and_punctuation_dont_matter():
    store, _ = store_with_his_words("גרתי בְּרָמַת גַּן, ליד הפארק.")
    assert check(store, "רמת גן", "איפה גרת?", about=True) is None


def test_the_6_10_failure_case_now_fails_safely():
    """Notes ask for family names; the model invents them -> each rejected on the spot -> it never
    finishes a usable plan -> rejected, and the previous plan stays (the sweep rebuilds it later)."""
    store, sid = store_with_his_words("שלום")
    store.save_notes(PID, "Family and friends names only, no places.", "tomer")
    store.save_next_plan(PID, "old", {"steps": [{"kind": "opening"}], "primary_goal": {"type": "conversation",
                                                                                      "description": "x"}})
    invented = [("set_goal", {"type": "name_retrieval", "description": "Family names."}),
                ("add_practice", practice("דני", question="איך קוראים לחבר הכי קרוב שלך?")),
                ("add_practice", practice("מיכל", about=True)), ("finish", {})]
    client = FakeClient(tool_calls(*invented), tool_calls(*invented), text("I can't."))
    status = build_next_plan(store, client, SETTINGS, PID, sid, generate_fn=gen, today=dt.date(2026, 10, 6))
    assert status == "failed" and "didn't finish a usable plan" in store.get_session(PID, sid)["plan_error"]
    assert store.get_next_plan(PID)["built_after_session"] == "old"
    # the prompt tells the builder to collect names instead; the tool told it exactly what was wrong
    assert "COLLECT" in client.requests[0]["config"].system_instruction
    replies = [p.function_response.response for p in client.requests[1]["contents"][-1].parts]
    assert "דני is not in his data" in replies[1]["error"]


def test_report_tutor_issue_becomes_a_low_flag():
    draft = MemoryDraft(sections={}, word_bank={}, today=dt.date(2026, 10, 6))
    tools = {t.name: t for t in build_memory_tools(draft)}
    tools["report_tutor_issue"].handler({"kind": "invented_fact", "tutor_said": "התכוונתי לרונית",
                                         "he_said": "על איזה רונית את מדברת?",
                                         "what_went_wrong": "She gave a name he says he doesn't know."})
    flag = draft.flags[0]
    assert (flag.kind.value, flag.severity.value, flag.issue) == ("tutor_issue", "low", "invented_fact")
    assert (flag.tutor_said, flag.he_said) == ("התכוונתי לרונית", "על איזה רונית את מדברת?")
    assert flag.evidence == "She gave a name he says he doesn't know."  # English only


def test_word_bank_is_not_proof_of_his_life():
    """The 6.10 invented names landed in the word bank; that must not make them 'known'."""
    store, _ = store_with_his_words("שלום")
    memory = {**MEMORY, "word_bank": {"רונית": {"attempts": 1, "failed": 1}}}
    known = grounding_text(store, PID, memory, "", "")
    step = PracticeStep(**practice("רונית", question="בת המשפחה שמארגנת את החגים שלך"))
    assert "not in his data" in practice_checker(known, set())(step)


def test_a_rejected_step_is_fixed_on_the_spot():
    store, sid = store_with_his_words("שלום")
    calls = build_calls(names=("דני", "עכו"))  # דני is invented: rejected, the rest goes on
    calls[2] = ("add_practice", practice("דני", question="החבר הכי קרוב שלך"))
    calls.insert(3, ("add_practice", practice("פארק הירקון", about=True)))  # the fix
    client = FakeClient(tool_calls(*calls), text("done"))
    status = build_next_plan(store, client, SETTINGS, PID, sid, generate_fn=gen, today=dt.date(2026, 10, 6))
    assert status == "done"
    names = [s["name"] for s in store.get_next_plan(PID)["steps"] if s["kind"] == "practice"]
    assert names == ["פארק הירקון", "עכו"]
    assert store.get_session(PID, sid)["plan_tool_errors"] == 1


def test_failed_plans_are_retried_by_the_sweep_at_most_three_times():
    store, sid = store_with_his_words("שלום")
    store.update_session(PID, sid, {"plan_status": "pending"})
    for attempt in range(1, 4):
        assert store.pending_plan_sessions(PID) == [sid]
        build_next_plan(store, FakeClient(text("no plan")), SETTINGS, PID, sid, generate_fn=gen)
        assert store.get_session(PID, sid)["plan_attempts"] == attempt
    assert store.pending_plan_sessions(PID) == []  # stops: the quota isn't burned hourly forever
