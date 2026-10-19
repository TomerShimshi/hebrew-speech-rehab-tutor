"""The tutor's memory text (16): assembled by code from the checked memory sections -- every item
reaches her, nothing else does. It replaced a model rewrite that dropped checked items and carried
unsourced advice from version to version (an audit, 19.10).

The text is saved as `memory_prompt` (the tutor prompt, the plan builder, research and the
caregiver page read that field) after every memory update and every caregiver edit."""

from app.schemas import MAX_ITEMS_PER_SECTION

# The sections, in the order she reads them, with their headings.
SECTIONS = (
    ("personal_facts", "About him (people, places, events he told you about)"),
    ("interests", "His interests"),
    ("what_works", "What helped him when he got stuck"),
    ("what_to_avoid", "What to avoid"),
    ("language_observations", "How he speaks"),
    ("homework_given", "Homework you gave him"),
)


def render_memory(memory: dict | None) -> str:
    """The memory section of her instructions. Newest items first in each section (they're appended
    in order); empty sections are left out. "" only for an account that has had no session."""
    memory = memory or {}
    sections = memory.get("sections") or {}
    sessions = int(memory.get("sessions_processed") or 0)
    lines: list[str] = []
    if sessions:
        lines.append(f"You have talked with him {sessions} time{'s' if sessions != 1 else ''} before.")
    recent = memory.get("recent_summaries") or []
    if recent:
        last = recent[-1]
        lines += ["", f"Last time ({last.get('date', '')}):", str(last.get("summary", "")).strip()]
    for key, heading in SECTIONS:
        items = [str(i).strip() for i in (sections.get(key) or []) if str(i).strip()]
        if not items:
            continue
        lines += ["", f"{heading}:"] + [f"- {i}" for i in reversed(items[-MAX_ITEMS_PER_SECTION:])]
    return "\n".join(lines).strip()
