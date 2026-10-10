"""The tutor's full system instruction for a session (one place, used by the session start
and by the caregiver page's "prompt for the next session" view -- so what the page shows is
exactly what the tutor gets)."""

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from app.class_plan import plan_for_session, render_class_plan
from app.config import Settings
from app.deps import games_for
from app.games import recent_games_line
from app.prompts import TutorPrompt, render_tutor_prompt
from app.schemas import ClassPlan
from app.store import ENDED, SessionStore

TZ = ZoneInfo("Asia/Jerusalem")  # his local time: "yesterday" and "this morning" are his
# A session he actually talked in (the same bar as the reminder's "practised today", 11).
MIN_TURNS = 2


@dataclass
class SessionPrompt:
    prompt: TutorPrompt
    plan: ClassPlan | None
    games: object  # GamesSnapshot | None
    start_note: str  # the first note she gets on the Live socket (the greeting cue)


def memory_block(memory: dict | None) -> str:
    """The tutor-facing part of this account's memory (written after each session, 04)."""
    if not memory or not memory.get("memory_prompt"):
        return ""
    text = memory["memory_prompt"].strip()
    focus = memory.get("focus_next_session") or []
    if focus:
        text += "\n\nFocus for this session:\n" + "\n".join(f"- {f}" for f in focus)
    return text


def _part_of_day(t: dt.datetime) -> str:
    h = t.hour
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 21:
        return "evening"
    return "night"


def _day(d: dt.date) -> str:
    return f"{d:%A}, {d.day} {d:%B}"  # e.g. "Tuesday, 6 October"


def _days_ago(n: int) -> tuple[str, str, str]:
    """(English, the everyday Hebrew time word, an example opener using it). Loose, natural
    words -- "אתמול", "לפני כמה ימים" -- not exact counts: an exact phrase she was told to say
    word for word came out stiff ("שמחתי לשמוע אותך קודם")."""
    if n == 0:
        return ("earlier today", "השיחה האחרונה שלנו",
                "שמחה לדבר איתך שוב! מה חדש אצלך מאז השיחה האחרונה שלנו?")
    if n == 1:
        return "yesterday", "אתמול", "אתמול סיפרת לי על ..., איך היה היום?"
    if n < 14:
        return f"{n} days ago", "לפני כמה ימים", "לפני כמה ימים סיפרת לי על ..., מה שלומך מאז?"
    return (f"{n} days ago", "עבר קצת זמן",
            "עבר קצת זמן מאז שדיברנו, אני שמחה לשמוע אותך! מה שלומך?")


@dataclass
class SessionTiming:
    block: str  # the WHEN YOU LAST SPOKE section
    last_he: str | None  # e.g. "אתמול"; None on his first conversation
    example: str = ""  # an opener that uses it naturally
    last_he_en: str = ""  # "yesterday", "3 days ago"


def session_timing(store: SessionStore, pid: str, now: dt.datetime | None = None,
                   exclude_sid: str | None = None) -> SessionTiming:
    """Today's date and when they last talked -- computed in code from the session records, so
    the tutor never has to guess ("as we said yesterday" when it was earlier today)."""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(TZ)
    lines = [f"Today is {_day(now.date())} {now.year}, {_part_of_day(now)} (Israel time)."]
    past = [s for s in store.list_sessions(pid, 30)
            if s.get("id") != exclude_sid and s.get("status") == ENDED and s.get("started_at")
            and (s.get("turn_count") or 0) >= MIN_TURNS]
    if not past:
        lines.append("This is your FIRST conversation with him: there is no earlier conversation "
                     "to refer to.")
        return SessionTiming("\n".join(lines), None)
    last = past[0]["started_at"].astimezone(TZ)  # list_sessions is newest first
    ago = (now.date() - last.date()).days
    when, when_he, example = _days_ago(ago)
    if ago == 0:
        lines.append(f"Your last conversation with him was {when}, in the {_part_of_day(last)}.")
    else:
        lines.append(f"Your last conversation with him was {when} ({_day(last.date())}), "
                     f"in the {_part_of_day(last)}.")
    lines.append(f'In Hebrew, the natural way to refer to it: "{when_he}" (or simply "בפעם הקודמת" / '
                 f'"לאחרונה"). For example: "{example}"')
    week = sum(1 for s in past if (now.date() - s["started_at"].astimezone(TZ).date()).days < 7)
    lines.append(f"Conversations in the last 7 days: {week}. Total so far: {len(past)}"
                 + (" or more." if len(past) == 30 else "."))
    return SessionTiming("\n".join(lines), when_he, example, when)


def start_note(timing: SessionTiming) -> str:
    """The greeting cue -- the last thing she reads before speaking, so the timing goes here too
    (in the prompt alone she still said "yesterday" about a session from earlier today)."""
    if timing.last_he is None:
        when = "This is your first conversation with him."
    else:
        when = (f'You last talked with him {timing.last_he_en} ("{timing.last_he}"). If you mention '
                f'it, weave it into a natural, warm sentence, like: "{timing.example}" (the "..." is '
                f'something from what you remember about him).')
    return f"[The patient just opened the app. {when} Greet him and begin the session.]"


def build_session_prompt(store: SessionStore, settings: Settings, pid: str, profile_text: str,
                         games_reader, *, exclude_sid: str | None = None) -> SessionPrompt:
    # Today's lesson plan (05): the built plan, the intro plan for a new/reset account, or none.
    plan = plan_for_session(store, pid)
    # What he played in the Simon app lately -- fresh at every start, computed in code (06).
    games = games_for(pid, settings, games_reader)
    # On a reconnect the session already exists: it is "now", not the last conversation.
    timing = session_timing(store, pid, exclude_sid=exclude_sid)
    prompt = render_tutor_prompt(
        patient_profile=profile_text,
        session_timing=timing.block,
        memory_prompt=memory_block(store.get_memory(pid)),
        class_plan=render_class_plan(plan),
        games_recent=recent_games_line(games),
    )
    return SessionPrompt(prompt=prompt, plan=plan, games=games, start_note=start_note(timing))
