"""The write tools of the memory-update agent (call #2).

Each tool validates its arguments and applies them to an in-request MemoryDraft; nothing
touches Firestore until the whole update succeeds (then it's saved once, with history).
"""

import datetime as dt
from dataclasses import dataclass, field

from app import word_bank
from app.agent.runner import Tool
from app.patient_profile import AREA_NAMES, LEVELS, MAX_ABOUT, MAX_ABOUT_CHARS, MAX_VOCABULARY, MAX_VOCABULARY_CHARS
from app.schemas import (
    MAX_ITEM_CHARS,
    MAX_ITEMS_PER_SECTION,
    SECTION_NAMES,
    Flag,
    MemorySections,
    SessionSummary,
    WordResult,
    WordSource,
    WordStats,
)


@dataclass
class Inferring:
    """What the app infers about him (15.5), starting from what it inferred before: his needs per
    area and points for his therapist -- for every account; and, only without an uploaded profile
    (`profile`), a few lines about him and his own names."""
    about: list[str] = field(default_factory=list)
    vocabulary: list[str] = field(default_factory=list)  # newest first
    areas: dict[str, dict] = field(default_factory=dict)  # area -> {level, evidence, note, set_by, history, ...}
    changed: set[str] = field(default_factory=set)  # areas recorded in this session
    points: list[dict] = field(default_factory=list)  # for his therapist: {id, text, why, evidence, status, ...}
    new_points: list[dict] = field(default_factory=list)  # added in this session
    profile: bool = True  # False: he has an uploaded profile -- never inferred, never touched


def add_vocabulary(inferring: Inferring, word: str) -> None:
    """Newest first, no duplicates, capped: the oldest names drop off."""
    word = " ".join(str(word).split())
    if word and len(word) <= MAX_VOCABULARY_CHARS:
        inferring.vocabulary = [word, *[w for w in inferring.vocabulary if w != word]][:MAX_VOCABULARY]


@dataclass
class MemoryDraft:
    sections: MemorySections
    word_bank: dict[str, WordStats]
    today: dt.date
    summary: SessionSummary | None = None
    flags: list[Flag] = field(default_factory=list)
    # probe target -> "treated"/"untreated", from the plan the session used (05)
    probe_kinds: dict[str, str] = field(default_factory=dict)
    probe_results: list[dict] = field(default_factory=list)
    # names he found / couldn't find in free talk (12), for the session's caregiver view
    own_names: list[dict] = field(default_factory=list)
    names_game: dict | None = None  # {status, note} (12)
    sequencing: dict | None = None  # {told_order, needed_help, low_confidence, skipped, note} (14)
    inferring: Inferring | None = None  # no uploaded profile (15.5); None = the tools aren't offered
    focus: list[str] | None = None  # 2-4 focus points for the next session (16); None = keep the old ones


# What report_tutor_issue may report (8.5). Saved as a low-severity "tutor_issue" flag.
TUTOR_ISSUE_KINDS = ("invented_fact", "insisted", "wrong_language", "cut_off", "early_goodbye",
                     "confusing_question", "other")
NAMES_GAME_STATUSES = ("played", "skipped", "not_reached")
OWN_RESULTS = (WordResult.self_found, WordResult.not_found)

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
        low = args.get("asr_confidence") == "low"
        if args.get("probe") and result in OWN_RESULTS:
            raise ValueError("self_found / not_found are for names in free talk, never for names-game items: "
                             "use uncued / cued / failed with probe=true")
        if args.get("probe"):
            # an untreated names-game item stays untrained: asked, never practiced (12)
            source = WordSource.practiced if draft.probe_kinds.get(word) == "treated" else WordSource.probe
        elif result in OWN_RESULTS:
            source = WordSource(result.value)
        else:
            source = WordSource.practiced
        stats = word_bank.record(
            draft.word_bank.get(word), result, draft.today,
            cue_level=args.get("cue_level"), low_confidence=low, source=source,
        )
        draft.word_bank[word] = stats
        if result in OWN_RESULTS:
            draft.own_names = [r for r in draft.own_names if r["word"] != word]
            draft.own_names.append({"word": word, "result": result.value, "low_confidence": low})
        if args.get("probe"):
            # A check-in item from today's plan: also kept on the session for progress charts.
            draft.probe_results = [r for r in draft.probe_results if r["word"] != word]
            draft.probe_results.append({
                "word": word, "result": result.value,
                "kind": draft.probe_kinds.get(word, "untreated"),
                "low_confidence": args.get("asr_confidence") == "low",
            })
        return {"ok": True, "next_due": stats.next_due}

    def record_sequencing(args: dict) -> dict:
        told = args.get("told_order") or []
        if not isinstance(told, list) or not all(isinstance(t, (int, float)) for t in told):
            raise ValueError("told_order is a list of the events' numbers, e.g. [1, 3, 2, 4]")
        draft.sequencing = {"told_order": [int(t) for t in told], "needed_help": bool(args.get("needed_help")),
                            "low_confidence": bool(args.get("low_confidence")), "skipped": bool(args.get("skipped")),
                            "note": str(args.get("note", ""))[:300]}
        return {"ok": True}

    def record_names_game(args: dict) -> dict:
        status = args.get("status")
        if status not in NAMES_GAME_STATUSES:
            raise ValueError(f"status must be one of {list(NAMES_GAME_STATUSES)}")
        draft.names_game = {"status": status, "note": str(args.get("note", ""))[:300]}
        return {"ok": True}

    def record_needs(args: dict) -> dict:
        area = args.get("area")
        if area not in AREA_NAMES:
            raise ValueError(f"area must be one of {list(AREA_NAMES)}")
        evidence = [_norm(str(e))[:200] for e in (args.get("evidence") or []) if _norm(str(e))][:3]
        note = _norm(str(args.get("note", "")))[:300]
        if area == "goals":
            if not note:
                raise ValueError("for goals, the note says what he wants (in English)")
            level = "noted"
        else:
            level = args.get("level")
            if level not in LEVELS:
                raise ValueError(f"level must be one of {list(LEVELS)}")
            if not evidence:
                level = "unclear"  # no quote, no level: never a guess
        current = draft.inferring.areas.get(area) or {}
        if current.get("set_by") == "family":
            # The family's word wins: keep their level, add what the app heard as a note.
            draft.inferring.areas[area] = {**current, "app_note": note, "app_evidence": evidence,
                                           "app_level": level}
        else:
            draft.inferring.areas[area] = {**current, "level": level, "evidence": evidence, "note": note,
                                           "set_by": "app", "app_level": level}
        draft.inferring.changed.add(area)
        return {"ok": True, "level": draft.inferring.areas[area].get("level")}

    def suggest_for_therapist(args: dict) -> dict:
        text_ = _norm(str(args.get("point", "")))[:300]
        if not text_:
            raise ValueError("point is required (HEBREW, one short sentence the family can raise)")
        inf = draft.inferring
        if any(p.get("text") == text_ for p in inf.points + inf.new_points):
            raise ValueError("already on the list")
        if len(inf.new_points) >= 2:
            raise ValueError("at most two points per session: only what really matters")
        inf.new_points.append({"text": text_, "why": _norm(str(args.get("why", "")))[:300],
                               "evidence": [_norm(str(e))[:200] for e in (args.get("evidence") or []) if _norm(str(e))][:3],
                               "status": "new"})
        return {"ok": True}

    def update_profile(args: dict) -> dict:
        inf, field_, op = draft.inferring, args.get("field"), args.get("op")
        item = _norm(str(args.get("item", "")))
        if field_ not in ("about", "vocabulary") or op not in ("add", "remove"):
            raise ValueError("field is about|vocabulary, op is add|remove")
        if not item:
            raise ValueError("item is required")
        items = inf.about if field_ == "about" else inf.vocabulary
        if op == "remove":
            if item not in items:
                raise ValueError("not in the profile: copy the item exactly")
            items.remove(item)
            return {"ok": True}
        if field_ == "vocabulary":
            if len(item) > MAX_VOCABULARY_CHARS or len(item.split()) > 4:
                raise ValueError("a vocabulary item is ONE name or place, in Hebrew")
            add_vocabulary(inf, item)
            return {"ok": True, "vocabulary": len(inf.vocabulary)}
        if len(item) > MAX_ABOUT_CHARS:
            raise ValueError(f"too long (max {MAX_ABOUT_CHARS} characters): one short line")
        if item not in inf.about:
            if len(inf.about) >= MAX_ABOUT:
                raise ValueError(f"the profile has {MAX_ABOUT} lines: remove or merge one first")
            inf.about.append(item)
        return {"ok": True, "about": len(inf.about)}

    def set_focus(args: dict) -> dict:
        points = [_norm(str(p)) for p in (args.get("points") or []) if _norm(str(p))]
        if not 1 <= len(points) <= 4:
            raise ValueError("give 2-4 points (at least one)")
        if any(len(p) > MAX_ITEM_CHARS for p in points):
            raise ValueError(f"a point is at most {MAX_ITEM_CHARS} characters: keep each short and concrete")
        draft.focus = points
        return {"ok": True}

    def save_session_summary(args: dict) -> dict:
        draft.summary = SessionSummary(**args)
        return {"ok": True}

    def raise_flag(args: dict) -> dict:
        draft.flags.append(Flag(**args))
        return {"ok": True}

    def report_tutor_issue(args: dict) -> dict:
        kind = args.get("kind") or "other"
        if kind not in TUTOR_ISSUE_KINDS:
            raise ValueError(f"kind must be one of {list(TUTOR_ISSUE_KINDS)}")
        draft.flags.append(Flag(kind="tutor_issue", severity="low", issue=kind,
                                evidence=str(args.get("what_went_wrong", ""))[:1000],
                                tutor_said=str(args.get("tutor_said", ""))[:600],
                                he_said=str(args.get("he_said", ""))[:600]))
        return {"ok": True}

    str_list = {"type": "array", "items": {"type": "string"}}
    inferring_tools = [
        Tool(
            "record_needs",
            "Record how one AREA of his speech went in THIS session, from the transcript: after a check step in "
            "TODAY'S PLAN ('A short naming moment', ...); naming from the names game and practice; connected "
            "speech from a sequencing task or an activity; 'conversation' from how he talked throughout. Not a "
            "diagnosis: what you heard today. Call once per area this session showed; skip the others.",
            {
                "type": "object",
                "properties": {
                    "area": {"type": "string", "enum": list(AREA_NAMES)},
                    "level": {"type": "string", "enum": list(LEVELS), "description": (
                        "ok = no real difficulty; some_difficulty = some effort or errors; clear_difficulty = "
                        "often hard; unclear = not enough heard. Not used for goals.")},
                    "evidence": {**str_list, "description": "1-3 short quotes (HEBREW, exact) from the transcript. "
                                                             "None -> the level is 'unclear'."},
                    "note": {"type": "string", "description": (
                        "ENGLISH, one short sentence: what you noticed (for goals: what he wants to do better).")},
                },
                "required": ["area", "note"],
            },
            record_needs,
        ),
        Tool(
            "suggest_for_therapist",
            "RARELY (most sessions: none): a point the family could raise with his speech therapist -- a "
            "difficulty that keeps coming back over sessions (HIS NEEDS' history), a clear change, or something "
            "the app can't practice. Not something already on the list (POINTS FOR HIS THERAPIST). At most two.",
            {
                "type": "object",
                "properties": {
                    "point": {"type": "string", "description": (
                        "HEBREW, one short practical sentence for the family, e.g. 'כדאי לשאול אם לתרגל ...'.")},
                    "why": {"type": "string", "description": "ENGLISH, one sentence: what you saw, over which sessions."},
                    "evidence": {**str_list, "description": "1-3 short quotes (HEBREW, exact)."},
                },
                "required": ["point", "why"],
            },
            suggest_for_therapist,
        ),
        *([Tool(
            "update_profile",
            "HE HAS NO UPLOADED PROFILE: keep his inferred profile up to date from what HE said. about: a few "
            "short lines (ENGLISH) -- age range if he said, what he does or did, family, where he lives, interests, "
            "how he speaks. Only what he said; never guess. vocabulary: ONE name or place (HEBREW) he used or that "
            "matters to him (people, towns, places, brands) -- it helps the transcription hear him right. Don't add "
            "what's already there.",
            {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": ["about", "vocabulary"]},
                    "op": {"type": "string", "enum": ["add", "remove"]},
                    "item": {"type": "string", "description": "The line or the name (for remove: copied exactly)."},
                },
                "required": ["field", "op", "item"],
            },
            update_profile,
        )] if draft.inferring.profile else []),
    ] if draft.inferring is not None else []
    return [*inferring_tools,
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
            "Record how he did retrieving one specific name: one the tutor practiced or asked in the names "
            "game, OR one he went for on his own in free talk with visible effort (self_found / not_found).",
            {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "result": {"type": "string", "enum": [r.value for r in WordResult],
                               "description": ("uncued = on his own; cued = after a hint; failed = the tutor gave it; "
                                               "self_found / not_found = a name in free talk the tutor didn't practice or "
                                               "ask: he found it himself after visible effort / he tried and gave up or "
                                               "talked around it.")},
                    "cue_level": {"type": "string", "description": "Which hint worked, e.g. 'meaning', 'first syllable', 'sentence completion'."},
                    "asr_confidence": {"type": "string", "enum": ["high", "low"],
                                       "description": "low if the two transcript versions disagree about this word."},
                    "probe": {"type": "boolean",
                              "description": "true if this name was one of the NAMES GAME items in TODAY'S PLAN and she asked it there."},
                },
                "required": ["word", "result", "asr_confidence"],
            },
            record_word_result,
        ),
        Tool(
            "record_sequencing",
            "Record the SEQUENCING task of TODAY'S PLAN (only if the plan has one): the order he told the events in. "
            "Call once.",
            {
                "type": "object",
                "properties": {
                    "told_order": {"type": "array", "items": {"type": "integer"}, "description": (
                        "The events' numbers (as numbered in TODAY'S PLAN, the correct order) in the order HE told "
                        "them, matched by meaning (the transcript mishears); events he left out are absent. His "
                        "first full telling, before her help.")},
                    "needed_help": {"type": "boolean", "description": "true if she had to help with the order."},
                    "low_confidence": {"type": "boolean", "description": (
                        "true if the two transcript versions disagree in a way that changes the order.")},
                    "skipped": {"type": "boolean", "description": "true if she didn't run it (e.g. he was tired)."},
                    "note": {"type": "string", "description": "ENGLISH, one short sentence: how it went."},
                },
                "required": ["told_order"],
            },
            record_sequencing,
        ),
        Tool(
            "record_names_game",
            "Record what happened to the NAMES GAME of TODAY'S PLAN (only if the plan has one). Call once.",
            {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": list(NAMES_GAME_STATUSES),
                               "description": ("played = she asked at least one game name; skipped = she chose not "
                                               "to (e.g. he was tired); not_reached = the session ended before it.")},
                    "note": {"type": "string", "description": "ENGLISH, one short sentence: how it went or why not."},
                },
                "required": ["status"],
            },
            record_names_game,
        ),
        Tool(
            "set_focus",
            "Set 2-4 concrete focus points for the NEXT session (ENGLISH), replacing the old ones: what to "
            "build on or practice, from THIS session (e.g. 'He enjoyed telling about the trip -- ask for the "
            "story in order'). Call once, after the memory updates.",
            {"type": "object", "properties": {"points": {**str_list, "description": "2-4 short points."}},
             "required": ["points"]},
            set_focus,
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
        Tool(
            "report_tutor_issue",
            "Report a mistake the TUTOR made in this session, for the family to review (e.g. she asked "
            "about a person or place that isn't part of his life). Not for his own difficulties.",
            {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(TUTOR_ISSUE_KINDS)},
                    "tutor_said": {"type": "string", "description": "HEBREW: her words, quoted exactly (just the relevant part)."},
                    "he_said": {"type": "string", "description": "HEBREW: his reply, quoted exactly (empty if none)."},
                    "what_went_wrong": {"type": "string", "description": "ENGLISH: one short sentence, no Hebrew sentences."},
                },
                "required": ["kind", "tutor_said", "what_went_wrong"],
            },
            report_tutor_issue,
        ),
    ]
