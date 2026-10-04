"""Builds the Live tutor's system instruction from prompts/tutor.yaml."""

from dataclasses import dataclass
from pathlib import Path

import yaml

from app.config import REPO_ROOT

TUTOR_PROMPT_PATH = REPO_ROOT / "prompts" / "tutor.yaml"

# Rendered in this order; each becomes a titled section of the system instruction.
_SECTIONS = (
    ("language", "LANGUAGE"),
    ("role", "ROLE"),
    ("style_rules", "STYLE RULES"),
    ("session_structure", "SESSION STRUCTURE"),
    ("fatigue_protocol", "FATIGUE AND FRUSTRATION"),
    ("safety", "SAFETY"),
    ("patient_profile", "PATIENT PROFILE"),
    ("memory_prompt", "WHAT YOU REMEMBER FROM PREVIOUS SESSIONS"),
    ("games_recent", "HIS GAMES APP"),
    ("class_plan", "TODAY'S PLAN"),
)


@dataclass(frozen=True)
class TutorPrompt:
    version: str
    text: str


def read_optional_text(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def render_tutor_prompt(
    *,
    patient_profile: str = "",
    memory_prompt: str = "",
    games_recent: str = "",
    class_plan: str = "",
    template_path: Path = TUTOR_PROMPT_PATH,
) -> TutorPrompt:
    template = yaml.safe_load(template_path.read_text(encoding="utf-8"))
    values = {
        "patient_profile": patient_profile,
        "memory_prompt": memory_prompt,
        "games_recent": games_recent,
        "class_plan": class_plan,
    }
    parts = []
    for key, title in _SECTIONS:
        body = template.get(key, "")
        used = [name for name in values if "{" + name + "}" in body]
        if used and not any(values[name].strip() for name in used):
            continue  # its placeholder is empty: drop the whole section (incl. any guidance text)
        # str.replace, not str.format: the Hebrew examples and future content may contain braces.
        for name, value in values.items():
            body = body.replace("{" + name + "}", value)
        body = body.strip()
        if body:
            parts.append(f"## {title}\n{body}")
    return TutorPrompt(version=str(template["prompt_version"]), text="\n\n".join(parts))
