"""Caregiver corrections to the tutor's memory (sub-plan 08).

Speech recognition can put a wrong "fact" into the memory (a misheard name). The caregiver
can remove one item, or restore an earlier version. Either way the replaced memory goes into
memory_history first (so the change can be undone), and the caller backs it up to the bucket.

Removing an item also rewrites memory_prompt -- the summary the tutor actually reads -- with
one small SUMMARY_MODEL call, so the fact is gone from both places. If that call fails,
nothing is changed.
"""

import datetime as dt
import sys

from google.genai import types

from app.agent.memory_update import _models, load_prompts
from app.config import Settings
from app.llm import generate
from app.schemas import SECTION_NAMES
from app.store import SessionStore

MIN_KEEP_RATIO = 0.3  # a rewritten summary shorter than this (vs the old one) is a broken reply


class MemoryEditError(Exception):
    pass


def _log(message: str) -> None:
    print(f"[memory_edit] {message}", file=sys.stderr, flush=True)


def _stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")  # unique even for two edits in one second


def _without_meta(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in ("updated_at", "version")}


def remove_item(store: SessionStore, client, settings: Settings, pid: str, section: str, item: str,
                *, generate_fn=generate) -> dict:
    """Removes one item from a memory section and rewrites the tutor's summary without it.
    Returns the new memory. Raises MemoryEditError (nothing changed) on bad input or failure."""
    if section not in SECTION_NAMES:
        raise MemoryEditError(f"unknown section {section!r}")
    current = store.get_memory(pid)
    if not current:
        raise MemoryEditError("no memory")
    items = list((current.get("sections") or {}).get(section) or [])
    if item not in items:
        raise MemoryEditError("item not found (the memory may have changed; reload)")
    items.remove(item)

    old_summary = current.get("memory_prompt", "")
    summary = old_summary
    if old_summary.strip():
        prompt = load_prompts()["remove_fact"]
        result = generate_fn(client, _models(settings),
                             f"# FACT TO REMOVE\n{item}\n\n# CURRENT SUMMARY\n{old_summary}",
                             types.GenerateContentConfig(system_instruction=prompt, temperature=0.1))
        summary = (result.response.text or "").strip()
        if len(summary) < MIN_KEEP_RATIO * len(old_summary.strip()):
            raise MemoryEditError("the rewritten summary looks broken; nothing was changed")
        _log(f"{pid}: summary rewritten without a {section} item ({len(old_summary)} -> {len(summary)} chars)")

    new = {**_without_meta(current), "memory_prompt": summary,
           "sections": {**(current.get("sections") or {}), section: items}}
    # The replaced version keeps its updated_at: the history is listed (and sorted) by it.
    store.save_memory(pid, f"edit-{_stamp()}", new, current)
    return new


def remove_word(store: SessionStore, pid: str, word: str) -> dict:
    """Removes one word from the word bank (e.g. a name the plan invented). No model call."""
    current = store.get_memory(pid)
    bank = dict((current or {}).get("word_bank") or {})
    if word not in bank:
        raise MemoryEditError("word not found (the memory may have changed; reload)")
    bank.pop(word)
    new = {**_without_meta(current), "word_bank": bank}
    store.save_memory(pid, f"edit-{_stamp()}", new, current)
    _log(f"{pid}: removed a word from the word bank")
    return new


def restore_version(store: SessionStore, pid: str, version: str) -> dict:
    """Makes an earlier memory version current; the current one goes into the history."""
    old = store.get_memory_version(pid, version)
    if not old or not old.get("memory_prompt"):
        raise MemoryEditError("version not found")
    current = store.get_memory(pid)
    restored = _without_meta(old)
    store.save_memory(pid, f"restore-{_stamp()}", restored, current)
    _log(f"{pid}: restored memory version {version}")
    return restored
