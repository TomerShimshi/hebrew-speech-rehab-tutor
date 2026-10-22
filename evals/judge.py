"""The judge shared by the evals: one structured-output call per tutor turn, by meaning (the transcript's
punctuation is unreliable). Its prompt is prompts/eval_judge.yaml; it is checked against hand-labeled
cases with `python -m evals.check_judge`."""

from functools import lru_cache

import yaml
from google.genai import types
from pydantic import BaseModel

from app.config import REPO_ROOT, Settings
from app.llm import text_client

JUDGE_MODEL = "gemini-3.8-flash"
PROMPT_PATH = REPO_ROOT / "prompts" / "eval_judge.yaml"


class Verdict(BaseModel):
    reacted: bool  # her turn opens with a reaction to his answer
    reaction: str  # its words, or ""
    real_questions: int  # separate questions (or requests to speak) she asks him
    invites_answer: bool  # the turn ends with something for him to answer
    reads_instructions: bool  # app / instruction text said aloud


@lru_cache
def prompt() -> dict:
    return yaml.safe_load(PROMPT_PATH.read_text(encoding="utf-8"))


@lru_cache
def _client():
    return text_client(Settings().gemini_api_key)


def judge(his: str, her: str) -> Verdict:
    r = _client().models.generate_content(
        model=JUDGE_MODEL, contents=f"HE SAID: {his or '(nothing: the session starts)'}\nSHE SAID: {her}",
        config=types.GenerateContentConfig(system_instruction=prompt()["judge"], response_mime_type="application/json",
                                           response_schema=Verdict, temperature=0))
    return r.parsed if isinstance(r.parsed, Verdict) else Verdict.model_validate_json(r.text)
