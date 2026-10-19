"""16: the tutor's memory text is assembled by code -- every section item reaches her, nothing else."""
from app.memory_text import SECTIONS, render_memory
from app.schemas import MAX_ITEMS_PER_SECTION

MEMORY = {
    "sessions_processed": 3,
    "recent_summaries": [{"date": "2026-10-17", "summary": "Older session."},
                         {"date": "2026-10-18", "summary": "Talked about a trip to עכו."}],
    "sections": {
        "personal_facts": ["Lives near the sea", "Has two grandchildren"],
        "interests": ["Trips up north"],
        "what_works": ["A first-sound cue brought 'נהריה' at once"],
        "what_to_avoid": [],
        "language_observations": ["Pauses before names of places"],
        "homework_given": ["Think of one place to tell about"],
    },
}


def test_every_item_reaches_her_and_nothing_else():
    text = render_memory(MEMORY)
    for items in MEMORY["sections"].values():
        for item in items:
            assert f"- {item}" in text, item
    assert "Last time (2026-10-18):\nTalked about a trip to עכו." in text  # only the latest session
    assert "Older session." not in text
    assert "What to avoid" not in text  # an empty section is left out
    assert text.startswith("You have talked with him 3 times before.")
    bullets = [line for line in text.splitlines() if line.startswith("- ")]
    assert len(bullets) == sum(len(v) for v in MEMORY["sections"].values())  # no extra advice


def test_sections_in_order_newest_first_and_capped():
    text = render_memory(MEMORY)
    headings = [h for key, h in SECTIONS if MEMORY["sections"][key]]
    assert [text.index(h) for h in headings] == sorted(text.index(h) for h in headings)
    assert text.index("- Has two grandchildren") < text.index("- Lives near the sea")  # newest first
    many = {"sessions_processed": 1, "sections": {"interests": [f"i{n}" for n in range(MAX_ITEMS_PER_SECTION + 5)]}}
    rendered = render_memory(many)
    assert "- i0\n" not in rendered + "\n" and f"- i{MAX_ITEMS_PER_SECTION + 4}" in rendered


def test_no_session_no_text():
    assert render_memory(None) == "" and render_memory({}) == ""
