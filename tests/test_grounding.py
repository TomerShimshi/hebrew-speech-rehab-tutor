"""8.5: the plan must never invent his people -- the case from Tomer's session on 6.10.26.
Since 12 the check-in is the names game's stable set, so the rule covers practice items and
the set's names."""

import datetime as dt

from app import llm
from app.agent.memory_tools import MemoryDraft, build_memory_tools
from app.agent.next_class import build_next_plan, enforce_plan_rules, enforce_set_rules, grounding_text
from app.config import Settings
from app.schemas import CheckInProposal
from app.store import InMemorySessionStore
from app.transcripts import EndReason, TurnIn
from fake_llm import FakeClient, text
from test_class_plan import a_plan

PID = "tomer@example.com"
SETTINGS = Settings(summary_model="primary", summary_fallback_models="fallback")
MEMORY = {"memory_prompt": "He likes Nahariya beach (חוף נהריה) and lived in Ramat Gan (רמת גן).",
          "sections": {"personal_facts": ["Lived in רמת גן and enjoyed פארק הירקון"]},
          "word_bank": {"מצפה רמון": {"attempts": 1}}}


def practice(target, elicit, about=False):
    return {"target": target, "elicit": elicit, "hint_meaning": "m", "hint_first_syllable": "s",
            "sentence_completion": "c", "about_his_life": about}


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


def test_invented_people_are_dropped_known_ones_kept():
    store, _ = store_with_his_words("יש לי אישה קוראים לה שיר")
    known = grounding_text(store, PID, MEMORY, "", "")
    plan = a_plan(practice=[
        practice("דני", "איך קוראים לחבר שקרוב אליך במיוחד?"),                 # personal by wording -> invented
        practice("רונית", "מי מארגנת את החגים במשפחה?", about=True),              # marked personal -> invented
        practice("שיר", "איך קוראים לאשתך?"),                                       # he said it himself
        practice("פארק הירקון", "באיזה פארק טיילת כשגרת ברמת גן?", about=True),  # in the memory
        practice("עכו", "העיר העתיקה עם החומות בצפון"),                           # general knowledge
    ])
    kept = enforce_plan_rules(plan, untreated=set(), known=known)
    assert [p.target for p in kept.practice] == ["שיר", "פארק הירקון", "עכו"]


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
    known = grounding_text(store, PID, {}, "", "")
    plan = a_plan(practice=[practice("רמת גן", "איפה גרת?", about=True), practice("עכו", "x")])
    assert [p.target for p in enforce_plan_rules(plan, set(), known).practice] == ["רמת גן", "עכו"]


def test_the_6_10_failure_case_now_fails_safely():
    """Notes ask for family names; the model invents them -> dropped -> nothing left to practice
    on a names day -> rejected, and the previous plan stays (the sweep rebuilds it later)."""
    store, sid = store_with_his_words("שלום")
    store.save_notes(PID, "Family and friends names only, no places.", "tomer")
    store.save_next_plan(PID, "old", a_plan().model_dump(mode="json"))
    invented = a_plan(practice=[practice("דני", "איך קוראים לחבר הכי קרוב שלך?"),
                                practice("מיכל", "מי החברה שאתה בקשר איתה?", about=True),
                                practice("אבי", "יש חבר ותיק שלך מהצבא?", about=True)])
    client = FakeClient(text("{}", parsed=invented), text("{}", parsed=invented))  # invents twice
    status = build_next_plan(store, client, SETTINGS, PID, sid, generate_fn=gen, today=dt.date(2026, 10, 6))
    assert status == "failed" and "no usable practice items" in store.get_session(PID, sid)["plan_error"]
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
    plan = a_plan(practice=[practice("רונית", "בת המשפחה שמארגנת את החגים שלך"), practice("עכו", "x")])
    assert [p.target for p in enforce_plan_rules(plan, set(), known).practice] == ["עכו"]


def test_a_retry_that_stops_inventing_is_accepted():
    store, sid = store_with_his_words("שלום")
    invented = a_plan(practice=[practice("דני", "החבר הכי קרוב שלך"), practice("מיכל", "החברה שלך", about=True)])
    honest = a_plan(practice=[practice("עכו", "העיר העתיקה עם החומות"),
                              practice("פארק הירקון", "הפארק שטיילת בו כשגרת ברמת גן", about=True)])
    client = FakeClient(text("{}", parsed=invented), text("{}", parsed=honest))
    status = build_next_plan(store, client, SETTINGS, PID, sid, generate_fn=gen, today=dt.date(2026, 10, 6))
    assert status == "done"
    assert [p["target"] for p in store.get_next_plan(PID)["practice"]] == ["עכו", "פארק הירקון"]


def test_failed_plans_are_retried_by_the_sweep_at_most_three_times():
    store, sid = store_with_his_words("שלום")
    store.update_session(PID, sid, {"plan_status": "pending"})
    bad = a_plan(practice=[practice("דני", "החבר הכי קרוב שלך")])  # invented: nothing left on a names day
    for attempt in range(1, 4):
        assert store.pending_plan_sessions(PID) == [sid]
        build_next_plan(store, FakeClient(text("{}", parsed=bad), text("{}", parsed=bad)), SETTINGS, PID, sid,
                        generate_fn=gen)
        assert store.get_session(PID, sid)["plan_attempts"] == attempt
    assert store.pending_plan_sessions(PID) == []  # stops: the quota isn't burned hourly forever
