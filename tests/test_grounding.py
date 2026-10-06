"""8.5: the plan must never invent his people -- the case from Tomer's session on 6.10.26."""

import datetime as dt

from app import llm
from app.agent.memory_tools import MemoryDraft, build_memory_tools
from app.agent.next_class import build_next_plan, enforce_plan_rules, grounding_text
from app.config import Settings
from app.store import InMemorySessionStore
from app.transcripts import EndReason, TurnIn
from fake_llm import FakeClient, text
from test_class_plan import a_plan

PID = "tomer@example.com"
SETTINGS = Settings(summary_model="primary", summary_fallback_models="fallback")
MEMORY = {"memory_prompt": "He likes Caesarea beach (חוף קיסריה) and lived in Ramat Gan (רמת גן).",
          "sections": {"personal_facts": ["Lived in רמת גן and enjoyed פארק הירקון"]},
          "word_bank": {"זכרון יעקב": {"attempts": 1}}}


def probe(target, elicit, about=False, bridge=""):
    return {"target": target, "kind": "untreated", "elicit": elicit, "bridge": bridge, "about_his_life": about}


def store_with_his_words(*lines):
    store = InMemorySessionStore()
    sid = store.create_session(PID, user_email=PID, model="m", prompt_version="v")
    store.upsert_turns(PID, sid, [TurnIn(seq=i, speaker="patient", text=t, t_start_s=i) for i, t in enumerate(lines)])
    store.end_session(PID, sid, EndReason.tutor_goodbye)
    store.save_memory(PID, sid, MEMORY, None)
    return store, sid


def test_invented_people_are_dropped_known_ones_kept():
    store, _ = store_with_his_words("יש לי אישה קוראים לה שיר")
    known = grounding_text(store, PID, MEMORY, "", "")
    plan = a_plan(probe=[
        probe("דני", "איך קוראים לחבר שקרוב אליך במיוחד?"),                 # personal by wording -> invented
        probe("רונית", "מי מארגנת את החגים במשפחה?", about=True),              # marked personal -> invented
        probe("שיר", "איך קוראים לאשתך?"),                                       # he said it himself
        probe("פארק הירקון", "באיזה פארק טיילת כשגרת ברמת גן?", about=True),  # in the memory
        probe("עכו", "העיר העתיקה עם החומות בצפון"),                           # general knowledge
    ], practice=[])
    kept = enforce_plan_rules(plan, practiced=set(), known=known)
    assert [p.target for p in kept.probe] == ["שיר", "פארק הירקון", "עכו"]


def test_vowel_marks_and_punctuation_dont_matter():
    store, _ = store_with_his_words("גרתי בְּרָמַת גַּן, ליד הפארק.")
    known = grounding_text(store, PID, {}, "", "")
    plan = a_plan(probe=[probe("רמת גן", "איפה גרת?", about=True), probe("עכו", "x"), probe("צפת", "y")], practice=[])
    assert [p.target for p in enforce_plan_rules(plan, set(), known).probe] == ["רמת גן", "עכו", "צפת"]


def test_the_6_10_failure_case_now_fails_safely():
    """Notes ask for family names; the model invents them -> dropped -> plan too thin -> rejected,
    and the previous plan stays (the sweep rebuilds it later)."""
    store, sid = store_with_his_words("שלום")
    store.save_notes(PID, "Family and friends names only, no places.", "tomer")
    store.save_next_plan(PID, "old", a_plan().model_dump(mode="json"))
    invented = a_plan(probe=[probe("דני", "איך קוראים לחבר הכי קרוב שלך?"),
                             probe("מיכל", "מי החברה שאתה בקשר איתה?", about=True),
                             probe("אבי", "יש חבר ותיק שלך מהצבא?", about=True)], practice=[])
    client = FakeClient(text("{}", parsed=invented), text("{}", parsed=invented))  # invents twice
    status = build_next_plan(store, client, SETTINGS, PID, sid, generate_fn=lambda c, m, ct, cf=None: llm.generate(
        c, m, ct, cf, sleep=lambda s: None), today=dt.date(2026, 10, 6))
    assert status == "failed" and "usable probe items" in store.get_session(PID, sid)["plan_error"]
    assert store.get_next_plan(PID)["built_after_session"] == "old"
    # the prompt tells the builder to collect names instead, and the retry says what was invented
    assert "COLLECT" in client.requests[0]["config"].system_instruction
    assert "you invented them: דני, מיכל, אבי" in client.requests[1]["contents"]


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
    plan = a_plan(probe=[probe("רונית", "בת המשפחה שמארגנת את החגים שלך"), probe("עכו", "x"),
                         probe("צפת", "y"), probe("טבריה", "z")], practice=[])
    assert [p.target for p in enforce_plan_rules(plan, set(), known).probe] == ["עכו", "צפת", "טבריה"]


def test_a_retry_that_stops_inventing_is_accepted():
    store, sid = store_with_his_words("שלום")
    invented = a_plan(probe=[probe("דני", "החבר הכי קרוב שלך"), probe("מיכל", "החברה שלך", about=True),
                             probe("אבי", "החבר שלך מהצבא", about=True)], practice=[])
    honest = a_plan(probe=[probe("עכו", "העיר העתיקה עם החומות"), probe("צפת", "עיר המקובלים"),
                           probe("פארק הירקון", "הפארק שטיילת בו כשגרת ברמת גן", about=True)], practice=[])
    client = FakeClient(text("{}", parsed=invented), text("{}", parsed=honest))
    status = build_next_plan(store, client, SETTINGS, PID, sid, generate_fn=lambda c, m, ct, cf=None: llm.generate(
        c, m, ct, cf, sleep=lambda s: None), today=dt.date(2026, 10, 6))
    assert status == "done"
    assert [p["target"] for p in store.get_next_plan(PID)["probe"]] == ["עכו", "צפת", "פארק הירקון"]



def test_failed_plans_are_retried_by_the_sweep_at_most_three_times():
    store, sid = store_with_his_words("שלום")
    store.update_session(PID, sid, {"plan_status": "pending"})
    bad = a_plan(probe=[], practice=[])
    gen = lambda c, m, ct, cf=None: llm.generate(c, m, ct, cf, sleep=lambda s: None)  # noqa: E731
    for attempt in range(1, 4):
        assert store.pending_plan_sessions(PID) == [sid]
        build_next_plan(store, FakeClient(text("{}", parsed=bad)), SETTINGS, PID, sid, generate_fn=gen)
        assert store.get_session(PID, sid)["plan_attempts"] == attempt
    assert store.pending_plan_sessions(PID) == []  # stops: the quota isn't burned hourly forever
