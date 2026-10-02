"""The write tools of the memory-update agent (call #2).

Each tool validates its arguments and applies them to an in-request MemoryDraft; nothing
touches Firestore until the whole update succeeds (then it's saved once, with history).
"""

import datetime as dt
from dataclasses import dataclass, field

from app import word_bank
from app.agent.runner import Tool
from app.schemas import (
    MAX_ITEM_CHARS,
    MAX_ITEMS_PER_SECTION,
    SECTION_NAMES,
    Flag,
    MemorySections,
    SessionSummary,
    WordResult,
    WordStats,
)


@dataclass
class MemoryDraft:
    sections: MemorySections
    word_bank: dict[str, WordStats]
    today: dt.date
    summary: SessionSummary | None = None
    flags: list[Flag] = field(default_factory=list)


def _norm(text: str) -> str:
    return " ".join(text.split()).strip()


def build_memory_tools(draft: MemoryDraft) -> list[Tool]:
    def update_memory(args: dict) -> dict:
        section, op = args.get("section"), args.get("op")
        if section not in SECTION_NAMES:
            raise ValueError(f"section must be one of {', '.join(SECTION_NAMES)}")
        item = _norm(str(args.get("item", "")))
        if not item:
            raise ValueError("item is required")
        if len(item) > MAX_ITEM_CHARS:
            raise ValueError(f"item too long (max {MAX_ITEM_CHARS} characters): keep it short")
        items: list[str] = getattr(draft.sections, section)
        if op == "add":
            if item in items:
                return {"ok": True, "note": "already in memory"}
            if len(items) >= MAX_ITEMS_PER_SECTION:
                raise ValueError(f"section full ({MAX_ITEMS_PER_SECTION} items): replace or remove an old item")
            items.append(item)
        elif op in ("replace", "remove"):
            if item not in items:
                raise ValueError(f"item not found in {section}; copy it exactly as shown in the memory")
            if op == "remove":
                items.remove(item)
            else:
                new_item = _norm(str(args.get("new_item", "")))
                if not new_item or len(new_item) > MAX_ITEM_CHARS:
                    raise ValueError(f"new_item is required (max {MAX_ITEM_CHARS} characters)")
                items[items.index(item)] = new_item
        else:
            raise ValueError("op must be add, replace or remove")
        return {"ok": True, "section_size": len(items)}

    def record_word_result(args: dict) -> dict:
        word = _norm(str(args.get("word", "")))
        if not word or len(word) > 60:
            raise ValueError("word is required (a single word or short name)")
        result = WordResult(args.get("result"))
        stats = word_bank.record(
            draft.word_bank.get(word), result, draft.today,
            cue_level=args.get("cue_level"),
            low_confidence=args.get("asr_confidence") == "low",
        )
        draft.word_bank[word] = stats
        return {"ok": True, "next_due": stats.next_due}

    def save_session_summary(args: dict) -> dict:
        draft.summary = SessionSummary(**args)
        return {"ok": True}

    def raise_flag(args: dict) -> dict:
        draft.flags.append(Flag(**args))
        return {"ok": True}

    str_list = {"type": "array", "items": {"type": "string"}}
    return [
        Tool(
            "update_memory",
            "Add, replace or remove ONE short item in a section of the long-term memory about him. "
            "Use 'replace'/'remove' with the item copied exactly from the current memory.",
            {
                "type": "object",
                "properties": {
                    "section": {"type": "string", "enum": list(SECTION_NAMES)},
                    "op": {"type": "string", "enum": ["add", "replace", "remove"]},
                    "item": {"type": "string", "description": "The item (for replace/remove: the existing one)."},
                    "new_item": {"type": "string", "description": "Only for replace: the new text."},
                },
                "required": ["section", "op", "item"],
            },
            update_memory,
        ),
        Tool(
            "record_word_result",
            "Record how he did retrieving one specific word or name the tutor practiced with him.",
            {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "result": {"type": "string", "enum": [r.value for r in WordResult],
                               "description": "uncued = on his own; cued = after a hint; failed = the tutor gave it."},
                    "cue_level": {"type": "string", "description": "Which hint worked, e.g. 'meaning', 'first syllable', 'sentence completion'."},
                    "asr_confidence": {"type": "string", "enum": ["high", "low"],
                                       "description": "low if the two transcript versions disagree about this word."},
                },
                "required": ["word", "result", "asr_confidence"],
            },
            record_word_result,
        ),
        Tool(
            "save_session_summary",
            "Save the summary of THIS session. Call exactly once.",
            {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "3-6 sentences, in English."},
                    "topics": str_list,
                    "mood": {"type": "string", "enum": ["good", "ok", "low", "unknown"]},
                    "highlights": str_list,
                    "difficulties": str_list,
                },
                "required": ["summary", "topics", "mood"],
            },
            save_session_summary,
        ),
        Tool(
            "raise_flag",
            "Flag something the family should see: a sudden decline vs previous sessions, distress, "
            "a safety concern, or a technical problem that disrupted the session.",
            {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["sudden_decline", "distress", "safety", "technical"]},
                    "severity": {"type": "string", "enum": ["low", "high"]},
                    "evidence": {"type": "string", "description": "Quote or describe what you saw."},
                },
                "required": ["kind", "severity", "evidence"],
            },
            raise_flag,
        ),
    ]
