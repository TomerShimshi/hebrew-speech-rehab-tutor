"""The tutor knows today's date and when they last talked -- from the records, not a guess."""

import datetime as dt

from app.prompts import render_tutor_prompt
from app.session_prompt import session_timing, start_note
from app.store import ENDED, InMemorySessionStore
from conftest import DAD


def session_timing_block(*args, **kw):
    return session_timing(*args, **kw).block


# 8.10.2026 is a Thursday; 10:00 in Israel = 07:00 UTC (summer time)
NOW = dt.datetime(2026, 10, 8, 7, 0, tzinfo=dt.timezone.utc)


def add_session(store, started, turns=10, status=ENDED):
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    store.update_session(DAD, sid, {"started_at": started, "status": status, "turn_count": turns})
    return sid


def test_first_conversation():
    text = session_timing_block(InMemorySessionStore(), DAD, NOW)
    assert text.startswith("Today is Thursday, 8 October 2026, morning (Israel time).")
    assert "FIRST conversation" in text


def test_yesterday_evening_in_israel_time():
    store = InMemorySessionStore()
    add_session(store, dt.datetime(2026, 10, 7, 16, 30, tzinfo=dt.timezone.utc))  # 19:30 Israel
    text = session_timing_block(store, DAD, NOW)
    assert "was yesterday (Wednesday, 7 October), in the evening." in text
    assert "last 7 days: 1. Total so far: 1." in text


def test_late_utc_evening_is_already_the_next_day_in_israel():
    store = InMemorySessionStore()
    add_session(store, dt.datetime(2026, 10, 7, 22, 0, tzinfo=dt.timezone.utc))  # 01:00 on the 8th
    assert "was earlier today, in the night." in session_timing_block(store, DAD, NOW)


def test_newest_real_session_counts_and_short_or_current_ones_dont():
    store = InMemorySessionStore()
    add_session(store, NOW - dt.timedelta(days=12))
    add_session(store, NOW - dt.timedelta(days=4))
    add_session(store, NOW - dt.timedelta(days=2), turns=1)  # opened and closed: not a conversation
    current = add_session(store, NOW - dt.timedelta(minutes=5), turns=0, status="active")
    text = session_timing_block(store, DAD, NOW, exclude_sid=current)
    assert "was 4 days ago (Sunday, 4 October)" in text
    assert "last 7 days: 1. Total so far: 2." in text


def test_rendered_as_its_own_section_with_the_no_guessing_rule():
    text = render_tutor_prompt(session_timing="Today is X.").text
    assert "## WHEN YOU LAST SPOKE" in text and "Never guess or invent when you last spoke" in text
    assert "## WHEN YOU LAST SPOKE" not in render_tutor_prompt().text


def test_hebrew_phrase_and_the_greeting_cue():
    store = InMemorySessionStore()
    assert "first conversation" in start_note(session_timing(store, DAD, NOW))
    add_session(store, NOW - dt.timedelta(days=1))
    timing = session_timing(store, DAD, NOW)
    assert 'the natural way to refer to it: "אתמול"' in timing.block
    note = start_note(timing)
    assert 'You last talked with him yesterday ("אתמול")' in note and "אתמול סיפרת לי על" in note
    for days, word in ((0, "השיחה האחרונה שלנו"), (3, "לפני כמה ימים"), (10, "לפני כמה ימים"), (20, "עבר קצת זמן")):
        store = InMemorySessionStore()
        add_session(store, NOW - dt.timedelta(days=days, minutes=30))
        assert session_timing(store, DAD, NOW).last_he == word
