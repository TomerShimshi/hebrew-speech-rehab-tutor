"""Validated transcript turns, as sent by the browser.

Saving is deterministic -- plain code, no LLM. Each caption line has a sequence number;
a line can keep growing (her text streams in, his line later gets Gemini's transcript),
so the browser re-sends changed lines and we UPSERT by seq: retries never duplicate.
"""

from enum import Enum

from pydantic import BaseModel, Field

MAX_TURNS_PER_BATCH = 50
MAX_TEXT_CHARS = 5000


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


class TurnsBatch(BaseModel):
    turns: list[TurnIn] = Field(max_length=MAX_TURNS_PER_BATCH)


class EndRequest(BaseModel):
    reason: EndReason = EndReason.end_button


def turn_doc_id(seq: int) -> str:
    return f"{seq:05d}"  # zero-padded: document ids sort in conversation order
