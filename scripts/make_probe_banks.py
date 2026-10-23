"""Writes candidate items for the fixed measurement banks of plan 17.5 (repetition, understanding,
clarity), under strict rules, checked by code and by a second model call. The output goes to a file
OUTSIDE the repo; a person reads it before the items go into prompts/probe_<area>.yaml (the banks are
fixed once in: measurement must compare like with like). Like the story bank (17).

    python -m scripts.make_probe_banks <area> <out.json>     area: repetition | understanding | clarity
"""

import json
import re
import sys

from google.genai import types
from pydantic import BaseModel

from app.agent.research import personal_terms
from app.config import Settings
from app.llm import text_client
from app.patient_profile import account_profile
from app.store import FirestoreSessionStore

MODEL = "gemini-3.8-flash"


class Item(BaseModel):
    level: int
    text: str  # HEBREW: what she says
    answer: str = ""  # understanding: "כן" / "לא", or the parts he should give; else ""


class Batch(BaseModel):
    items: list[Item]


class Check(BaseModel):
    ok: bool
    problem: str


SPECS = {
    "repetition": (
        "Hebrew items an adult REPEATS after a speech tutor, to measure repetition. Simple, common, everyday "
        "words only; no names, no numbers. level 1: one word of 2-3 syllables (12 items). level 2: a phrase of "
        "3-4 words (12 items). level 3: a sentence of 7-10 words (12 items).",
        lambda it: {1: (1, 1), 2: (3, 4), 3: (7, 10)}[it.level]),
    "understanding": (
        "Hebrew items to measure SPOKEN UNDERSTANDING (voice only -- nothing to point at or do). level 1: a "
        "simple yes/no question about an everyday fact (10). level 2: a yes/no comparison (10). level 3: a "
        "reversible yes/no ('אם דני גבוה מיוסי, האם יוסי נמוך מדני?') (10). level 4: a two-part spoken request "
        "he answers in words ('תגיד לי X, ואחר כך Y') (8). level 5: a three-part spoken request (6). answer: "
        "'כן'/'לא' for yes/no; for requests, the parts he should answer, in order, separated by ' | '. Answers "
        "must be unambiguous for any adult; for requests, about his own preferences (no right/wrong content).",
        lambda it: (3, 25)),
    "clarity": (
        "Short everyday Hebrew phrases an adult says CLEARLY after a tutor, to measure speech clarity: 4-6 "
        "words, varied sounds (ש/ס, ר, ל, ק/כ, consonant clusters), natural sentences. level 1 only (30).",
        lambda it: (4, 6)),
}

PROMPT = """{spec}
Rules for every item: modern, natural, everyday Hebrew; common words only; nothing sad or medical; no
names of people or places; no brands. Return the items as JSON."""


def personal() -> set[str]:
    st = FirestoreSessionStore()
    terms = set()
    for pid in st.list_patient_ids():  # never a name or place from any account's life
        terms |= personal_terms(st.get_memory(pid) or {}, account_profile(st, pid).text)
    return {t for t in terms if len(t) >= 3}


def main() -> None:
    area, out = sys.argv[1], sys.argv[2]
    spec, words = SPECS[area]
    client = text_client(Settings().gemini_api_key)
    r = client.models.generate_content(model=MODEL, contents=PROMPT.format(spec=spec),
                                       config=types.GenerateContentConfig(response_mime_type="application/json",
                                                                          response_schema=Batch, temperature=0.6))
    items = (r.parsed if isinstance(r.parsed, Batch) else Batch.model_validate_json(r.text)).items
    terms = personal()
    kept, rejected = [], []
    for it in items:
        n = len(it.text.split())
        lo, hi = words(it)
        why = []
        if not lo <= n <= hi:
            why.append(f"{n} words")
        if re.search(r"[A-Za-z0-9]", it.text):
            why.append("latin letters or digits")
        if any(t in it.text for t in terms):
            why.append("a personal term")
        if area == "understanding" and it.level <= 3 and it.answer not in ("כן", "לא"):
            why.append(f"answer {it.answer!r}")
        if not why:
            c = client.models.generate_content(model=MODEL, contents=[
                f"A Hebrew item for a speech-therapy measure ({area}): {it.text!r}"
                + (f" -- expected answer: {it.answer!r}" if it.answer else "") +
                ". Is it natural, correct, everyday Hebrew" + (", and is the expected answer unambiguously right "
                "for any adult" if area == "understanding" else "") + "? ok=false with the problem if not."],
                config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=Check,
                                                   temperature=0))
            v = c.parsed if isinstance(c.parsed, Check) else Check.model_validate_json(c.text)
            if not v.ok:
                why.append(v.problem[:80])
        (rejected if why else kept).append((it, why))
    json.dump([it.model_dump() for it, _ in kept], open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{area}: {len(items)} candidates, {len(kept)} kept")
    for it, why in rejected:
        print(f"  REJECTED [{it.level}] {it.text} -- {'; '.join(why)}")
    for it, _ in kept:
        print(f"  [{it.level}] {it.text}" + (f"  => {it.answer}" if it.answer else ""))


if __name__ == "__main__":
    main()
