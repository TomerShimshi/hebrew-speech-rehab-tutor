import datetime as dt

from app import llm, word_bank
from app.agent.memory_tools import MemoryDraft, build_memory_tools
from app.agent.memory_update import format_transcript, run_memory_update
from app.config import Settings
from app.schemas import ConsolidatedMemory, MemorySections, WordResult
from app.store import InMemorySessionStore
from app.transcripts import EndReason, TurnIn
from fake_llm import FakeClient, server_error, text, tool_calls

TODAY = dt.date(2026, 10, 1)
PID = "p1"
SETTINGS = Settings(summary_model="primary", summary_fallback_models="fallback")


def gen(client, models, contents, config=None):
    return llm.generate(client, models, contents, config, sleep=lambda s: None)


# ---- word bank --------------------------------------------------------------------------

def test_word_bank_spacing():
    s = word_bank.record(None, WordResult.uncued, TODAY)
    assert (s.interval_days, s.next_due) == (1, "2026-10-02")
    s = word_bank.record(s, WordResult.uncued, TODAY)
    assert s.interval_days == 2
    s = word_bank.record(s, WordResult.cued, TODAY, cue_level="first syllable")
    assert (s.interval_days, s.last_cue_level) == (1, "first syllable")
    s = word_bank.record(s, WordResult.failed, TODAY, low_confidence=True)
    assert (s.interval_days, s.next_due, s.failed, s.low_confidence, s.attempts) == (0, "2026-10-01", 1, 1, 4)


def test_word_bank_interval_cap_and_due_list():
    s = None
    for _ in range(10):
        s = word_bank.record(s, WordResult.uncued, TODAY)
    assert s.interval_days == word_bank.MAX_INTERVAL_DAYS
    bank = {"טבריה": word_bank.record(None, WordResult.failed, TODAY), "חיפה": s}
    assert word_bank.due_words(bank, TODAY) == ["טבריה"]


# ---- tools ------------------------------------------------------------------------------

def tools_for(draft):
    return {t.name: t.handler for t in build_memory_tools(draft)}


def test_update_memory_add_replace_remove_and_validation():
    draft = MemoryDraft(MemorySections(), {}, TODAY)
    t = tools_for(draft)
    t["update_memory"]({"section": "interests", "op": "add", "item": "  RPG   games "})
    assert draft.sections.interests == ["RPG games"]
    assert t["update_memory"]({"section": "interests", "op": "add", "item": "RPG games"})["note"] == "already in memory"
    t["update_memory"]({"section": "interests", "op": "replace", "item": "RPG games", "new_item": "RPG games (Witcher 3)"})
    assert draft.sections.interests == ["RPG games (Witcher 3)"]
    t["update_memory"]({"section": "interests", "op": "remove", "item": "RPG games (Witcher 3)"})
    assert draft.sections.interests == []
    for bad in (
        {"section": "secrets", "op": "add", "item": "x"},
        {"section": "interests", "op": "add", "item": ""},
        {"section": "interests", "op": "add", "item": "x" * 201},
        {"section": "interests", "op": "remove", "item": "not there"},
        {"section": "interests", "op": "explode", "item": "x"},
    ):
        try:
            t["update_memory"](bad)
            raise AssertionError(f"accepted {bad}")
        except ValueError:
            pass


def test_section_cap():
    draft = MemoryDraft(MemorySections(interests=[f"i{n}" for n in range(25)]), {}, TODAY)
    try:
        tools_for(draft)["update_memory"]({"section": "interests", "op": "add", "item": "one more"})
        raise AssertionError("cap not enforced")
    except ValueError as exc:
        assert "full" in str(exc)


def test_other_tools():
    draft = MemoryDraft(MemorySections(), {}, TODAY)
    t = tools_for(draft)
    t["record_word_result"]({"word": "טבריה", "result": "cued", "cue_level": "first syllable", "asr_confidence": "low"})
    assert draft.word_bank["טבריה"].low_confidence == 1
    t["save_session_summary"]({"summary": "Talked about games.", "topics": ["games"], "mood": "good"})
    assert draft.summary.mood.value == "good"
    t["raise_flag"]({"kind": "distress", "severity": "high", "evidence": "said he feels hopeless"})
    assert draft.flags[0].kind.value == "distress"


# ---- the full update --------------------------------------------------------------------

def make_session(store, lines):
    sid = store.create_session(PID, user_email="dad@example.com", model="m", prompt_version="v")
    store.upsert_turns(PID, sid, [TurnIn(seq=i, speaker=sp, text=tx, live_text=lv, t_start_s=i * 5)
                                  for i, (sp, tx, lv) in enumerate(lines)])
    store.end_session(PID, sid, EndReason.tutor_goodbye)
    return sid


CONVERSATION = [
    ("tutor", "שלום! על מה תרצה לדבר היום?", ""),
    ("patient", "על הטיול לגליל", "על הטיול לגליל"),
    ("tutor", "איזה כיף. איזו עיר ליד הכנרת?", ""),
    ("patient", "טבריה", "טבריה"),
]


def consolidated(prompt="He enjoys the Galilee. Last session: the trip to Tiberias."):
    return text("{}", parsed=ConsolidatedMemory(memory_prompt=prompt, focus_next_session=["names of places"]))


def test_full_update_saves_memory_history_and_session_fields():
    store = InMemorySessionStore()
    sid = make_session(store, CONVERSATION)
    client = FakeClient(
        tool_calls(
            ("save_session_summary", {"summary": "Talked about a trip to the Galilee.", "topics": ["Galilee"], "mood": "good"}),
            ("update_memory", {"section": "interests", "op": "add", "item": "Trips to the Galilee"}),
            ("record_word_result", {"word": "טבריה", "result": "uncued", "asr_confidence": "high"}),
        ),
        text("done"),
        consolidated(),
    )
    status = run_memory_update(store, client, SETTINGS, PID, sid, today=TODAY, generate_fn=gen)
    assert status == "done"
    memory = store.get_memory(PID)
    assert memory["memory_prompt"].startswith("He enjoys the Galilee")
    assert memory["sections"]["interests"] == ["Trips to the Galilee"]
    assert memory["word_bank"]["טבריה"]["uncued"] == 1
    assert memory["focus_next_session"] == ["names of places"]
    assert memory["sessions_processed"] == 1
    assert memory["recent_summaries"][0]["mood"] == "good"
    session = store.get_session(PID, sid)
    assert session["memory_status"] == "done"
    assert session["summary"] == "Talked about a trip to the Galilee."
    assert session["memory_tool_calls"] == 3
    assert (PID, sid) not in store.memory_history  # there was no previous memory

    # a second session keeps the old memory in history and builds on it
    sid2 = make_session(store, CONVERSATION)
    client2 = FakeClient(text("nothing new"), consolidated("Second version."))
    assert run_memory_update(store, client2, SETTINGS, PID, sid2, today=TODAY, generate_fn=gen) == "done"
    assert store.memory_history[(PID, sid2)]["memory_prompt"].startswith("He enjoys the Galilee")
    assert store.get_memory(PID)["sections"]["interests"] == ["Trips to the Galilee"]  # kept
    assert store.get_memory(PID)["sessions_processed"] == 2
    # the agent saw the current memory and the transcript in its context
    context = client2.requests[0]["contents"][0].parts[0].text
    assert "Trips to the Galilee" in context and "טבריה" in context


def test_short_session_is_skipped_without_calling_the_model():
    store = InMemorySessionStore()
    sid = make_session(store, [("tutor", "שלום", ""), ("patient", "היי", "היי")])
    client = FakeClient()
    assert run_memory_update(store, client, SETTINGS, PID, sid, today=TODAY, generate_fn=gen) == "skipped"
    assert client.requests == []
    assert store.get_session(PID, sid)["memory_status"] == "skipped"


def test_model_outage_marks_failed_then_a_retry_succeeds():
    store = InMemorySessionStore()
    sid = make_session(store, CONVERSATION)
    down = FakeClient(*[server_error() for _ in range(6)])
    assert run_memory_update(store, down, SETTINGS, PID, sid, today=TODAY, generate_fn=gen) == "failed"
    session = store.get_session(PID, sid)
    assert session["memory_status"] == "failed" and "LLMUnavailable" in session["memory_error"]
    assert store.get_memory(PID) is None  # nothing half-written
    assert store.pending_memory_sessions(PID) == [sid]  # will be retried
    up = FakeClient(text("ok"), consolidated())
    assert run_memory_update(store, up, SETTINGS, PID, sid, today=TODAY, generate_fn=gen) == "done"
    assert store.pending_memory_sessions(PID) == []


def test_a_session_is_processed_only_once():
    store = InMemorySessionStore()
    sid = make_session(store, CONVERSATION)
    client = FakeClient(text("ok"), consolidated())
    assert run_memory_update(store, client, SETTINGS, PID, sid, today=TODAY, generate_fn=gen) == "done"
    assert run_memory_update(store, FakeClient(), SETTINGS, PID, sid, today=TODAY, generate_fn=gen) == "not_claimed"
    # an active (not ended) session can't be claimed either
    active = store.create_session(PID, user_email="d", model="m", prompt_version="v")
    assert not store.claim_for_memory(PID, active)


def test_transcript_formatting_shows_both_versions_when_they_differ():
    out = format_transcript([
        {"speaker": "tutor", "text": "מה שלומך?", "t_start_s": 1.0, "interrupted": True},
        {"speaker": "patient", "text": "אני לא יכול לסיים", "live_text": "אפשר לסיים", "t_start_s": 4.0},
        {"speaker": "patient", "text": "טוב", "live_text": "טוב", "t_start_s": 8.0},
    ])
    assert "(interrupted by him)" in out
    assert "browser caption: אפשר לסיים" in out
    assert out.count("browser caption") == 1  # identical versions aren't repeated
