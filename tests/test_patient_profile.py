from app.config import Settings
from app.patient_profile import CACHE_TTL_S, PatientProfileLoader, extract_vocabulary


def test_local_file_fallback_when_no_uri(tmp_path):
    f = tmp_path / "profile.md"
    f.write_text("local profile", encoding="utf-8")
    loader = PatientProfileLoader(Settings(patient_profile_uri=None, patient_profile_path=f))
    assert loader.get() == "local profile"


def test_reads_bucket_and_caches():
    calls = []
    now = [0.0]

    def fake_gcs(uri):
        calls.append(uri)
        return f"profile v{len(calls)}"

    settings = Settings(patient_profile_uri="gs://bucket/profile.md", patient_profile_path=None)
    loader = PatientProfileLoader(settings, read_gcs=fake_gcs, clock=lambda: now[0])
    assert loader.get() == "profile v1"
    assert loader.get() == "profile v1"  # cached
    now[0] = CACHE_TTL_S + 1
    assert loader.get() == "profile v2"  # refreshed after the TTL
    assert calls == ["gs://bucket/profile.md"] * 2


def test_bucket_failure_keeps_last_good_or_empty():
    now = [0.0]
    state = {"fail": True}

    def flaky(uri):
        if state["fail"]:
            raise RuntimeError("boom")
        return "good"

    settings = Settings(patient_profile_uri="gs://bucket/p.md", patient_profile_path=None)
    loader = PatientProfileLoader(settings, read_gcs=flaky, clock=lambda: now[0])
    assert loader.get() == ""  # never blocks a session
    state["fail"] = False
    assert loader.get() == "good"
    state["fail"] = True
    now[0] = CACHE_TTL_S + 1
    assert loader.get() == "good"  # keeps the last good copy


def test_extract_vocabulary():
    profile = "Some text\n- Vocabulary: ראש פינה, דני , כנרת\nvocabulary: דני, חיפה\nOther"
    assert extract_vocabulary(profile) == ["ראש פינה", "דני", "כנרת", "חיפה"]
    assert extract_vocabulary("no list here") == []
