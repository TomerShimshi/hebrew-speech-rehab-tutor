"""The tutor's full system instruction for a session (one place, used by the session start
and by the caregiver page's "prompt for the next session" view -- so what the page shows is
exactly what the tutor gets)."""

from dataclasses import dataclass

from app.class_plan import plan_for_session, render_class_plan
from app.config import Settings
from app.deps import games_for
from app.games import recent_games_line
from app.prompts import TutorPrompt, render_tutor_prompt
from app.schemas import ClassPlan
from app.store import SessionStore


@dataclass
class SessionPrompt:
    prompt: TutorPrompt
    plan: ClassPlan | None
    games: object  # GamesSnapshot | None


def memory_block(memory: dict | None) -> str:
    """The tutor-facing part of this account's memory (written after each session, 04)."""
    if not memory or not memory.get("memory_prompt"):
        return ""
    text = memory["memory_prompt"].strip()
    focus = memory.get("focus_next_session") or []
    if focus:
        text += "\n\nFocus for this session:\n" + "\n".join(f"- {f}" for f in focus)
    return text


def build_session_prompt(store: SessionStore, settings: Settings, pid: str, profile_text: str,
                         games_reader) -> SessionPrompt:
    # Today's lesson plan (05): the built plan, the intro plan for a new/reset account, or none.
    plan = plan_for_session(store, pid)
    # What he played in the Simon app lately -- fresh at every start, computed in code (06).
    games = games_for(pid, settings, games_reader)
    prompt = render_tutor_prompt(
        patient_profile=profile_text,
        memory_prompt=memory_block(store.get_memory(pid)),
        class_plan=render_class_plan(plan),
        games_recent=recent_games_line(games),
    )
    return SessionPrompt(prompt=prompt, plan=plan, games=games)
