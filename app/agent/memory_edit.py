"""Caregiver corrections to the tutor's memory (sub-plan 08).

Speech recognition can put a wrong "fact" into the memory (a misheard name). The caregiver
can remove one item, or restore an earlier version. Either way the replaced memory goes into
memory_history first (so the change can be undone), and the caller backs it up to the bucket.

The text the tutor reads (memory_prompt) is rendered by code from the sections (16), so after a
removal or a restore it is simply rendered again: the fact is gone at once, no model call.
"""

import datetime as dt
import re
import sys

from app.memory_text import SECTIONS, render_memory
from app.schemas import MAX_ITEM_CHARS, MAX_ITEMS_PER_SECTION, SECTION_NAMES
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


MAX_SUMMARY_CHARS = 1500  # a session summary's own limit (SessionSummary.summary)


class MemoryEditInvalid(MemoryEditError):
    """The new text itself is wrong (empty, too long, the section is full): a 422, not a 409."""


def _clean(text: str) -> str:
    text = " ".join(str(text or "").split())
    if not text:
        raise MemoryEditInvalid("empty text (to remove it, use remove)")
    if len(text) > MAX_ITEM_CHARS:
        raise MemoryEditInvalid(f"too long (at most {MAX_ITEM_CHARS} characters)")
    return text


def _section_items(store: SessionStore, pid: str, section: str) -> tuple[dict, list]:
    if section not in SECTION_NAMES:
        raise MemoryEditError(f"unknown section {section!r}")
    current = store.get_memory(pid)
    if not current:
        raise MemoryEditError("no memory")
    return current, list((current.get("sections") or {}).get(section) or [])


def _save(store: SessionStore, pid: str, current: dict, changes: dict, what: str) -> dict:
    new = {**_without_meta(current), **changes}
    new["memory_prompt"] = render_memory(new)
    _log(f"{pid}: {what}; the text re-rendered")
    store.save_memory(pid, f"edit-{_stamp()}", new, current)  # the replaced version is restorable
    return new


def edit_item(store: SessionStore, pid: str, section: str, old: str, new: str) -> dict:
    """Replaces one item with the family's text, at the same place (21). No model call."""
    text = _clean(new)
    current, items = _section_items(store, pid, section)
    if old not in items:
        raise MemoryEditError("item not found (the memory may have changed; reload)")
    items[items.index(old)] = text
    return _save(store, pid, current, {"sections": {**(current.get("sections") or {}), section: items}},
                 f"edited a {section} item")


def add_item(store: SessionStore, pid: str, section: str, text: str) -> dict:
    """Adds the family's item last, so it counts as newest and she reads it first (21)."""
    text = _clean(text)
    current, items = _section_items(store, pid, section)
    if text in items:
        raise MemoryEditError("already there")
    if len(items) >= MAX_ITEMS_PER_SECTION:
        raise MemoryEditInvalid(f"the section is full ({MAX_ITEMS_PER_SECTION}): remove one first")
    return _save(store, pid, current, {"sections": {**(current.get("sections") or {}), section: [*items, text]}},
                 f"added a {section} item")


def _summary_index(current: dict | None, date: str, old: str) -> int:
    recent = (current or {}).get("recent_summaries") or []
    for i, r in enumerate(recent):
        if r.get("date") == date and r.get("summary") == old:
            return i
    raise MemoryEditError("summary not found (the memory may have changed; reload)")


def edit_summary(store: SessionStore, pid: str, date: str, old: str, new: str) -> dict:
    """Corrects one session summary, found by its date and exact text (21)."""
    text = " ".join(str(new or "").split())
    if not text:
        raise MemoryEditInvalid("empty text (to remove it, use remove)")
    if len(text) > MAX_SUMMARY_CHARS:
        raise MemoryEditInvalid(f"too long (at most {MAX_SUMMARY_CHARS} characters)")
    current = store.get_memory(pid)
    i = _summary_index(current, date, old)
    recent = [dict(r) for r in current["recent_summaries"]]
    recent[i]["summary"] = text
    return _save(store, pid, current, {"recent_summaries": recent}, "edited a summary")


def remove_summary(store: SessionStore, pid: str, date: str, old: str) -> dict:
    current = store.get_memory(pid)
    i = _summary_index(current, date, old)
    recent = [r for j, r in enumerate(current["recent_summaries"]) if j != i]
    return _save(store, pid, current, {"recent_summaries": recent}, "removed a summary")


MAX_FOCUS = 4  # as many focus points as a memory update keeps


def edit_focus(store: SessionStore, pid: str, items: list[str]) -> dict:
    """Replaces the focus points for the next session with the family's (one per line; empty lines dropped)."""
    focus = [" ".join(str(i or "").split()) for i in items]
    focus = list(dict.fromkeys(f for f in focus if f))
    if len(focus) > MAX_FOCUS:
        raise MemoryEditInvalid(f"at most {MAX_FOCUS} focus points")
    if any(len(f) > MAX_ITEM_CHARS for f in focus):
        raise MemoryEditInvalid(f"too long (at most {MAX_ITEM_CHARS} characters a line)")
    current = store.get_memory(pid)
    if not current:
        raise MemoryEditError("no memory")
    return _save(store, pid, current, {"focus_next_session": focus}, "edited the focus points")


_LAST_TIME = re.compile(r"^Last time \((.*)\):$")


def edit_text(store: SessionStore, pid: str, old: str, text: str) -> dict:
    """The family edits her whole memory text (21). The text is rendered by code from the sections, so it
    is read back into them: each heading's "- " lines become that section (the top line is the newest),
    the "Last time" lines become the last summary. A heading left out empties its section; any other line
    is refused (it would be lost at the next render)."""
    current = store.get_memory(pid)
    if not current:
        raise MemoryEditError("no memory")
    if " ".join(old.split()) != " ".join((current.get("memory_prompt") or "").split()):
        raise MemoryEditError("the memory changed in the meantime (reload)")
    by_heading = {f"{heading}:": key for key, heading in SECTIONS}
    sections = {key: [] for key, _ in SECTIONS}
    summary, where, stray = None, None, []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or re.fullmatch(r"You have talked with him \d+ times? before\.", line):
            continue
        if line in by_heading:
            where = by_heading[line]
        elif _LAST_TIME.match(line):
            where, summary = "last_time", []
        elif where == "last_time" and summary is not None:
            summary.append(line)
        elif where in sections and line.startswith("-"):
            item = " ".join(line[1:].split())
            if item and item not in sections[where]:
                sections[where].append(item)
        else:
            stray.append(line)
    if stray:
        raise MemoryEditInvalid("lines outside a heading or not starting with \"- \": " + " | ".join(stray[:3]))
    for key, items in sections.items():
        if len(items) > MAX_ITEMS_PER_SECTION:
            raise MemoryEditInvalid(f"too many items under one heading (at most {MAX_ITEMS_PER_SECTION})")
        if any(len(i) > MAX_ITEM_CHARS for i in items):
            raise MemoryEditInvalid(f"an item is too long (at most {MAX_ITEM_CHARS} characters)")
    old_sections = current.get("sections") or {}
    # Items past what the text shows (older than the newest MAX_ITEMS_PER_SECTION) stay as they were.
    new_sections = {**old_sections, **{key: [*(old_sections.get(key) or [])[:-MAX_ITEMS_PER_SECTION], *reversed(items)]
                                       for key, items in sections.items()}}
    recent = [dict(r) for r in current.get("recent_summaries") or []]
    if summary is not None:
        joined = " ".join(" ".join(summary).split())
        if not joined:
            raise MemoryEditInvalid("the \"Last time\" summary is empty (to remove it, delete its heading too)")
        if len(joined) > MAX_SUMMARY_CHARS:
            raise MemoryEditInvalid(f"the summary is too long (at most {MAX_SUMMARY_CHARS} characters)")
        if not recent:
            raise MemoryEditInvalid("there is no session summary to edit")
        recent[-1]["summary"] = joined
    elif recent:
        recent.pop()  # the "Last time" block was deleted
    return _save(store, pid, current, {"sections": new_sections, "recent_summaries": recent}, "edited the whole text")


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
