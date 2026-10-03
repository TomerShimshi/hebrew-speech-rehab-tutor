from app.prompts import read_optional_text, render_tutor_prompt


def test_renders_all_fixed_sections_and_version():
    prompt = render_tutor_prompt()
    assert prompt.version
    for title in ("## ROLE", "## STYLE RULES", "## SESSION STRUCTURE", "## SAFETY"):
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
    assert "something special he'd like to talk about" in " ".join(text.split())
    assert "ALWAYS refer to yourself in the feminine" in text


def test_read_optional_text_handles_missing_file(tmp_path):
    assert read_optional_text(tmp_path / "missing.md") == ""
    assert read_optional_text(None) == ""
    f = tmp_path / "p.md"
    f.write_text("  profile  \n", encoding="utf-8")
    assert read_optional_text(f) == "profile"


def test_conversation_flow_rules_present():
    text = render_tutor_prompt().text
    assert "ONE THREAD AT A TIME" in text and "BRIDGE every change of topic" in text
    assert "do NOT start closing on your own" in text
    assert "say again" not in text.split("Closing")[1].split("Ending the call")[0].replace("Don't ask him to repeat or \"say again\" anything", "")
