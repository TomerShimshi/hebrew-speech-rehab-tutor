"""15: a profile per account, kept with the account -- uploaded on the caregiver page (inferred: 15.5)."""
from app.patient_profile import account_profile, extract_vocabulary
from app.store import InMemorySessionStore
from conftest import DAD, TOMER, FakeAuthTokens, auth

ASSESSMENT = "Man, 69, after a stroke.\n- Vocabulary: עין גדי, מצפה רמון"


def test_extract_vocabulary():
    profile = "Some text\n- Vocabulary: ראש פינה, דני , כנרת\nvocabulary: דני, חיפה\nOther"
    assert extract_vocabulary(profile) == ["ראש פינה", "דני", "כנרת", "חיפה"]
    assert extract_vocabulary("no list here") == []


def test_each_account_has_its_own_profile_or_none():
    store = InMemorySessionStore()
    store.save_profile(DAD, ASSESSMENT, "uploaded", TOMER)
    assert account_profile(store, DAD).text == ASSESSMENT and account_profile(store, DAD).source == "uploaded"
    none = account_profile(store, "cousin@example.com")
    assert (none.text, none.source) == ("", "")  # never someone else's
    store.save_profile(TOMER, "  ", "uploaded", TOMER)
    assert account_profile(store, TOMER).source == ""  # an empty profile is none


def config():
    return FakeAuthTokens.last_config.live_connect_constraints.config


def test_a_session_gets_only_its_own_profile_and_names(env):
    env.store.save_profile(DAD, ASSESSMENT, "uploaded", TOMER)
    env.client.post("/api/session/start", headers=auth())
    assert "Man, 69" in config().system_instruction.parts[0].text
    assert config().input_audio_transcription.custom_vocabulary == ["עין גדי", "מצפה רמון"]
    env.client.post("/api/session/start", headers=auth("tok-tomer"))  # an account without a profile
    text_ = config().system_instruction.parts[0].text
    assert "Man, 69" not in text_ and not config().input_audio_transcription.custom_vocabulary
    assert "still getting to know him" in " ".join(text_.split())


def test_the_family_uploads_it_on_the_caregiver_page(env):
    url = f"/api/caregiver/{DAD}/profile"
    assert env.client.get(f"/api/caregiver/{DAD}/overview", headers=auth("tok-tomer")).json()["profile"] is None
    r = env.client.put(url, headers=auth("tok-tomer"), json={"text": "  first version  "})
    assert r.status_code == 200
    saved = env.client.get(f"/api/caregiver/{DAD}/overview", headers=auth("tok-tomer")).json()["profile"]
    assert (saved["text"], saved["source"], saved["updated_by"]) == ("first version", "uploaded", TOMER)
    env.client.put(url, headers=auth("tok-tomer"), json={"text": ASSESSMENT})  # replaces it (backed up in prod)
    assert account_profile(env.store, DAD).text == ASSESSMENT
    assert env.client.put(url, headers=auth(), json={"text": "x"}).status_code == 403  # caregivers only
    assert env.client.put(url, headers=auth("tok-tomer"), json={"text": "x" * 8001}).status_code == 422
