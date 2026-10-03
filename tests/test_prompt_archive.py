import datetime as dt

from app.prompt_archive import PromptArchive, archive_name

WINTER = dt.datetime(2026, 1, 15, 14, 47, tzinfo=dt.timezone.utc)  # Israel = UTC+2
SUMMER = dt.datetime(2026, 7, 15, 13, 47, tzinfo=dt.timezone.utc)  # Israel = UTC+3 (DST)


def test_names_read_like_a_session_log_in_israel_time():
    assert archive_name("PLYI39zFIZabc", "regular-discourse", WINTER) == "2026-01-15_16-47_regular-discourse_PLYI39zF.md"
    assert archive_name("PLYI39zFIZabc", "intro", SUMMER) == "2026-07-15_16-47_intro_PLYI39zF.md"
    assert archive_name("abc", "", WINTER) == "2026-01-15_16-47_abc.md"
    assert archive_name("abc", "weird/../label!", WINTER) == "2026-01-15_16-47_weird-label_abc.md"


def test_save_uses_the_readable_name_and_records_the_session_id():
    saved = {}
    archive = PromptArchive("gs://b/debug/prompts", upload=lambda uri, text: saved.update({uri: text}))
    uri = archive.save(pid="dad@x.com", sid="PLYI39zFIZabc", prompt_text="PROMPT", label="intro",
                       meta={"session_id": "PLYI39zFIZabc"}, now=WINTER)
    assert uri == "gs://b/debug/prompts/dad@x.com/2026-01-15_16-47_intro_PLYI39zF.md"
    assert "PROMPT" in saved[uri] and "**session_id:** PLYI39zFIZabc" in saved[uri]
