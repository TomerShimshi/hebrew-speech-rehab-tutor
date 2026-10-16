from app.prompts import read_optional_text, render_tutor_prompt


def test_renders_all_fixed_sections_and_version():
    prompt = render_tutor_prompt()
    assert prompt.version
    for title in ("## ROLE", "## HOW YOU TALK", "## OPENING, TIMING AND CLOSING", "## SAFETY"):
        assert title in prompt.text


def test_empty_placeholders_drop_their_sections():
    text = render_tutor_prompt().text
    assert "{patient_profile}" not in text
    assert "{memory_prompt}" not in text
    assert "{class_plan}" not in text
    assert "## PATIENT PROFILE" not in text
    assert "## TODAY'S PLAN" not in text


def test_patient_profile_is_injected():
    text = render_tutor_prompt(patient_profile="Mild anomia for proper nouns.").text
    assert "## PATIENT PROFILE\nMild anomia for proper nouns." in text


def test_key_rules_present():
    text = render_tutor_prompt().text
    assert text.startswith("## LANGUAGE\nLANGUAGE RULE")  # Hebrew rule comes first
    assert "speak ONLY Modern Israeli Hebrew" in text
    assert "101" in text  # emergency number
    assert "ALWAYS refer to yourself in the feminine" in text


def test_read_optional_text_handles_missing_file(tmp_path):
    assert read_optional_text(tmp_path / "missing.md") == ""
    assert read_optional_text(None) == ""
    f = tmp_path / "p.md"
    f.write_text("  profile  \n", encoding="utf-8")
    assert read_optional_text(f) == "profile"


def test_conversation_flow_rules_present():
    text = " ".join(render_tutor_prompt().text.split())
    # one question at a time (12.10), explained; never two glued with "או ש" (16.10)
    assert "ONE QUESTION AT A TIME" in text and "Ask the one that matters more now" in text
    assert 'Never join two questions, or a remark and a question, with "או"' in text
    assert "NO summary, NO homework" in text and "end a TOPIC, not the session" in text  # no early goodbyes (12)
    # how the session works comes right after the role, and the steps stay behind the scenes
    with_steps = render_tutor_prompt(steps="Today's steps, in order: 1. opening.").text
    assert with_steps.index("## ROLE") < with_steps.index("## HOW THE SESSION WORKS") < with_steps.index("## HOW YOU TALK")
    flat = " ".join(with_steps.split())
    assert "He must never notice" in flat and "follow the HOW exactly" in flat and "FIRST call next_step" in flat
