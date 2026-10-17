"""docs/tools.md is generated from the code that declares the tools: it must stay in step."""
from app.tools_catalog import DOC_PATH, render


def test_the_tools_doc_is_up_to_date():
    assert DOC_PATH.read_text(encoding="utf-8") == render(), (
        "docs/tools.md is out of date: run `python -m app.tools_catalog`")


def test_every_agents_tools_are_listed():
    doc = render()
    for name in ("next_step", "end_session", "update_memory", "record_needs", "update_profile", "add_practice",
                 "add_sequencing", "finish", "add_game_homework", "research_technique", "web_search"):
        assert f"### `{name}`" in doc, name
    assert "## Error handling" in doc and "## Logging" in doc
