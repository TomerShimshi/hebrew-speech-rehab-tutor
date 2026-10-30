"""Validated transcript turns, as sent by the browser.

Saving is deterministic -- plain code, no LLM. Each caption line has a sequence number;
a line can keep growing (her text streams in, his line later gets Gemini's transcript),
so the browser re-sends changed lines and we UPSERT by seq: retries never duplicate.
"""

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

MAX_TURNS_PER_BATCH = 50
MAX_TEXT_CHARS = 5000
# A transcription marker, e.g. "<no speech detected>" (20): a closed pair, which speech never has
MARKER_RE = re.compile(r"<[^<>\n]{1,60}>")


class Speaker(str, Enum):
    patient = "patient"
    tutor = "tutor"


class EndReason(str, Enum):
    tutor_goodbye = "tutor_goodbye"
    end_button = "end_button"
    error = "error"
    abandoned = "abandoned"  # set by the server, for sessions whose tab was just closed


class TurnIn(BaseModel):
    seq: int = Field(ge=0, lt=100_000)
    speaker: Speaker
    text: str = Field(default="", max_length=MAX_TEXT_CHARS)  # Gemini's transcript
    live_text: str = Field(default="", max_length=MAX_TEXT_CHARS)  # browser recognizer (his lines)
    t_start_s: float = Field(ge=0)
    interrupted: bool = False
    matched_target: str | None = Field(default=None, max_length=80)  # the names-game name the page matched (20)


class NameLive(BaseModel):
    """One names-game name as the page saw it live (20): his transcripts, what matched, and the notes."""
    target: str = Field(max_length=200)
    gem: str = Field(default="", max_length=200)
    live: str = Field(default="", max_length=200)
    matched_by: Literal["gemini", "caption", ""] = ""
    early_note: bool = False  # she was told during his line
    she_accepted: bool | None = None  # her reply after it said he got it
    corrected: bool = False  # she was told afterwards, and corrected herself


class TurnsBatch(BaseModel):
    turns: list[TurnIn] = Field(max_length=MAX_TURNS_PER_BATCH)


class StepDone(BaseModel):
    """A step the tutor reported finished with next_step (13)."""
    done: str = Field(default="", max_length=200)
    how_it_went: str = Field(default="", max_length=400)
    at_s: float = Field(default=0, ge=0)


class StepHeld(BaseModel):
    """A next_step call the page held back (13.5): which step, why, when."""
    step: int = Field(default=0, ge=0, le=100)
    reason: str = Field(default="", max_length=40)  # "question" | "answers"
    at_s: float = Field(default=0, ge=0)


class StepUsage(BaseModel):
    """Gemini Live's usage while she was in one step (19): the step's cost in its trace."""
    prompt_tokens: int = Field(default=0, ge=0)
    response_tokens: int = Field(default=0, ge=0)
    audio_in_tokens: int = Field(default=0, ge=0)
    audio_out_tokens: int = Field(default=0, ge=0)
    usage_reports: int = Field(default=0, ge=0)


class LiveStats(BaseModel):
    """What the page saw of the live session (19), for its trace: the usage Gemini Live reported,
    her response times, the connection's troubles."""
    prompt_tokens: int = Field(default=0, ge=0)  # summed over the usage reports
    response_tokens: int = Field(default=0, ge=0)
    audio_in_tokens: int = Field(default=0, ge=0)
    audio_out_tokens: int = Field(default=0, ge=0)
    usage_reports: int = Field(default=0, ge=0)
    # the largest single report's total: if the reports are running totals (not per turn), this,
    # not the sum, is the session's usage -- kept to tell which (19.F)
    max_report_total: int = Field(default=0, ge=0)
    response_ms: list[int] = Field(default=[], max_length=300)  # end of his speech -> her first output
    reconnects: int = Field(default=0, ge=0)
    go_aways: int = Field(default=0, ge=0)
    by_step: list[StepUsage | None] = Field(default=[], max_length=41)  # the same usage, per step


class ContextEvent(BaseModel):
    """Something the page put into her context besides the voices (19): a note, her tool call, or the
    page's reply to it. Timed like the turns (seconds from the session's start)."""
    kind: str = Field(pattern="^(note|silent_note|call|reply)$")
    at_s: float = Field(default=0, ge=0)
    text: str = Field(default="", max_length=4000)  # a note
    id: str = Field(default="", max_length=200)  # a call and its reply
    name: str = Field(default="", max_length=80)
    args: dict = Field(default_factory=dict)
    response: dict = Field(default_factory=dict)


class ContextBatch(BaseModel):
    events: list[ContextEvent] = Field(default=[], max_length=400)


class EndRequest(BaseModel):
    reason: EndReason = EndReason.end_button
    steps_done: list[StepDone] = Field(default=[], max_length=40)  # steps mode (13)
    steps_held: list[StepHeld] = Field(default=[], max_length=60)
    live: LiveStats | None = None  # the session's trace (19)
    goodbye_refusals: int = Field(default=0, ge=0, le=20)  # end_session calls the page refused (20)
    names_live: list[NameLive] = Field(default=[], max_length=12)  # the names game, caught live (20)


def strip_markers(text: str) -> str:
    """The text without transcription markers ("<no speech detected>"), and without the spaces they
    left behind."""
    return " ".join(MARKER_RE.sub(" ", text or "").split())


def turn_doc_id(seq: int) -> str:
    return f"{seq:05d}"  # zero-padded: document ids sort in conversation order
