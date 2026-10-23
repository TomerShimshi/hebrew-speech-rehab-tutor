"""The judge shared by the evals: judges tutor turns by meaning (the transcript's punctuation is
unreliable). Its prompt is prompts/eval_judge.yaml; it is checked against hand-labeled cases with
`python -m evals.check_judge`.

Mindful of credit (22.10): turns are judged in BATCHES (one call for many turns), and every verdict is
cached on disk by the turn's text and the judge's prompt version -- judging the same turn again costs
nothing. The cache lives outside the repo (EVALS_CACHE, default: the system temp folder).
"""

import hashlib
import json
import os
import tempfile
from functools import lru_cache
from pathlib import Path

import yaml
from google.genai import types
from pydantic import BaseModel

from app.config import REPO_ROOT, Settings
from app.llm import text_client

JUDGE_MODEL = "gemini-3.8-flash"
PROMPT_PATH = REPO_ROOT / "prompts" / "eval_judge.yaml"
BATCH = 25  # turns per call
CACHE = Path(os.environ.get("EVALS_CACHE") or Path(tempfile.gettempdir()) / "hebrew_tutor_evals_judge_cache.json")


class Verdict(BaseModel):
    reacted: bool  # her turn opens with a reaction to his answer
    reaction: str  # its words, or ""
    real_questions: int  # separate questions (or requests to speak) she asks him
    invites_answer: bool  # the turn ends with something for him to answer
    reads_instructions: bool  # app / instruction text said aloud


class Numbered(Verdict):
    n: int  # the turn's number in the batch


class Batch(BaseModel):
    verdicts: list[Numbered]


@lru_cache
def prompt() -> dict:
    return yaml.safe_load(PROMPT_PATH.read_text(encoding="utf-8"))


@lru_cache
def _client():
    return text_client(Settings().gemini_api_key)


def _key(his: str, her: str) -> str:
    return hashlib.sha1(f"{prompt().get('prompt_version')}|{his}|{her}".encode("utf-8")).hexdigest()


def _load() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def judge_many(turns: list[tuple[str, str]]) -> list[Verdict]:
    """Verdicts for many (his, her) turns: cached ones free, the rest in batches of BATCH per call."""
    cache = _load()
    todo = [i for i, (his, her) in enumerate(turns) if _key(his, her) not in cache]
    for start in range(0, len(todo), BATCH):
        chunk = todo[start:start + BATCH]
        listing = "\n\n".join(f"TURN {n}\nHE SAID: {turns[i][0] or '(nothing: the session starts)'}\nSHE SAID: {turns[i][1]}"
                              for n, i in enumerate(chunk, 1))
        r = _client().models.generate_content(
            model=JUDGE_MODEL, contents=f"Judge each turn below separately; return one verdict per TURN number.\n\n{listing}",
            config=types.GenerateContentConfig(system_instruction=prompt()["judge"], response_mime_type="application/json",
                                               response_schema=Batch, temperature=0))
        got = r.parsed if isinstance(r.parsed, Batch) else Batch.model_validate_json(r.text)
        for v in got.verdicts:
            if 1 <= v.n <= len(chunk):
                i = chunk[v.n - 1]
                cache[_key(*turns[i])] = v.model_dump(exclude={"n"})
        CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    missing = [i for i, t in enumerate(turns) if _key(*t) not in cache]
    if missing:
        raise RuntimeError(f"the judge returned no verdict for {len(missing)} turn(s); run again (the rest is cached)")
    return [Verdict(**cache[_key(*t)]) for t in turns]


def judge(his: str, her: str) -> Verdict:
    return judge_many([(his, her)])[0]
