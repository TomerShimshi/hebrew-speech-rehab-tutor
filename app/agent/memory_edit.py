"""Caregiver corrections to the tutor's memory (sub-plan 08).

Speech recognition can put a wrong "fact" into the memory (a misheard name). The caregiver
can remove one item, or restore an earlier version. Either way the replaced memory goes into
memory_history first (so the change can be undone), and the caller backs it up to the bucket.

The text the tutor reads (memory_prompt) is rendered by code from the sections (16), so after a
removal or a restore it is simply rendered again: the fact is gone at once, no model call.
"""

import datetime as dt
import sys

from app.memory_text import render_memory
from app.schemas import SECTION_NAMES
from app.store import SessionStore


class MemoryEditError(Exception):
    pass


def _log(message: str) -> None:
    print(f"[memory_edit] {message}", file=sys.stderr, flush=True)


def _stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")  # unique even for two edits in one second


def _without_meta(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in ("updated_at", "version")}


def remove_item(store: SessionStore, pid: str, section: str, item: str) -> dict:
    """Removes one item from a memory section; the tutor's text is rendered again without it.
    Returns the new memory. Raises MemoryEditError (nothing changed) on bad input."""
    if section not in SECTION_NAMES:
        raise MemoryEditError(f"unknown section {section!r}")
    current = store.get_memory(pid)
    if not current:
        raise MemoryEditError("no memory")
    items = list((current.get("sections") or {}).get(section) or [])
    if item not in items:
        raise MemoryEditError("item not found (the memory may have changed; reload)")
    items.remove(item)

    new = {**_without_meta(current), "sections": {**(current.get("sections") or {}), section: items}}
    new["memory_prompt"] = render_memory(new)
    _log(f"{pid}: removed a {section} item; the text re-rendered")
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
    restored["memory_prompt"] = render_memory(restored)  # from its sections, as every text is now (16)
    store.save_memory(pid, f"restore-{_stamp()}", restored, current)
    _log(f"{pid}: restored memory version {version}")
    return restored
