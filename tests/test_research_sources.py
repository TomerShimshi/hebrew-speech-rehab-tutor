import io
import urllib.error

import pytest

from app import research_sources as rs


class FakeTavily:
    def __init__(self, results=None, error_code=None):
        self.results, self.error_code, self.calls = results or [], error_code, []

    def __call__(self, url, body, api_key):
        self.calls.append({"url": url, "body": body, "api_key": api_key})
        if self.error_code:
            raise urllib.error.HTTPError(url, self.error_code, "err", {}, io.BytesIO(b"{}"))
        return {"results": self.results}


RESULTS = [
    {"title": "SFA", "url": "https://www.asha.org/practice-portal/aphasia/", "content": "c" * 5000},
    {"title": "Review", "url": "https://pubmed.ncbi.nlm.nih.gov/24797214/", "content": "semantic feature analysis"},
    {"title": "Blog", "url": "https://blog.example/aphasia", "content": "tips"},
]


def test_trusted_scope_sends_the_domain_list(monkeypatch):
    fake = FakeTavily(RESULTS)
    monkeypatch.setattr(rs, "_post_json", fake)
    results = rs.web_search("KEY", "semantic feature analysis home practice")
    body = fake.calls[0]["body"]
    assert fake.calls[0]["api_key"] == "KEY" and body["search_depth"] == "basic"
    assert body["include_domains"] == list(rs.trusted_domains()) and "asha.org" in body["include_domains"]
    assert [r["trusted"] for r in results] == [True, True, False]
    assert len(results[0]["content"]) == rs.CONTENT_CHARS


def test_open_scope_has_no_domain_filter(monkeypatch):
    fake = FakeTavily(RESULTS)
    monkeypatch.setattr(rs, "_post_json", fake)
    rs.web_search("KEY", "aphasia hebrew", scope="open")
    assert "include_domains" not in fake.calls[0]["body"]
    with pytest.raises(ValueError):
        rs.web_search("KEY", "x", scope="everything")


@pytest.mark.parametrize("code", [401, 429, 432, 433])
def test_quota_and_key_errors_mean_unavailable(monkeypatch, code):
    monkeypatch.setattr(rs, "_post_json", FakeTavily(error_code=code))
    with pytest.raises(rs.TavilyUnavailable):
        rs.web_search("KEY", "anomia")


def test_other_errors_raise_normally(monkeypatch):
    monkeypatch.setattr(rs, "_post_json", FakeTavily(error_code=500))
    with pytest.raises(urllib.error.HTTPError):
        rs.web_search("KEY", "anomia")


def test_no_key_is_unavailable_without_a_call(monkeypatch):
    fake = FakeTavily(RESULTS)
    monkeypatch.setattr(rs, "_post_json", fake)
    with pytest.raises(rs.TavilyUnavailable):
        rs.web_search("", "anomia")
    assert fake.calls == []


def test_trusted_domains_match_subdomains_only():
    assert rs.is_trusted_domain("https://www.asha.org/a")
    assert rs.is_trusted_domain("https://pubmed.ncbi.nlm.nih.gov/1/")
    assert not rs.is_trusted_domain("https://asha.org.evil.example/")
    assert not rs.is_trusted_domain("https://notasha.org/")


@pytest.mark.parametrize("phrase", [
    "tDCS combined with naming therapy", "repetitive TMS", "transcranial direct current",
    "medication for aphasia", "pharmacological treatment", "thrombolytic therapy", "תרופות לאפזיה",
])
def test_medical_blocklist_catches(phrase):
    assert rs.is_medical(phrase)


@pytest.mark.parametrize("phrase", [
    "semantic feature analysis", "script training at home", "cueing hierarchy for word retrieval",
    "תרגול שיום בבית",
])
def test_medical_blocklist_allows_behavioral_practice(phrase):
    assert not rs.is_medical(phrase)


def test_personal_terms_in_queries():
    terms = {"Efraim", "חיפה", "Bo"}  # too-short terms are ignored (would match everywhere)
    assert rs.personal_terms_in("anomia for proper names like efraim", terms) == ["Efraim"]
    assert rs.personal_terms_in("שמות מקומות כמו חיפה", terms) == ["חיפה"]
    assert rs.personal_terms_in("word retrieval in Boston naming test", terms) == []


def test_duplicate_articles_are_dropped(monkeypatch):
    dup = [{"title": "Phonomotor vs SFA", "url": "https://pubs.asha.org/doi/abs/10.1044/x"},
           {"title": "Phonomotor vs SFA ", "url": "https://pubs.asha.org/doi/10.1044/x"}]
    monkeypatch.setattr(rs, "_post_json", FakeTavily(dup))
    assert [r["url"] for r in rs.web_search("KEY", "sfa")] == ["https://pubs.asha.org/doi/abs/10.1044/x"]


def test_duplicates_with_the_same_text_are_dropped(monkeypatch):
    dup = [{"title": "Errorless learning (abstract)", "url": "https://a.example/1", "content": "Same abstract text."},
           {"title": "Errorless learning", "url": "https://a.example/2", "content": "Same  abstract text."}]
    monkeypatch.setattr(rs, "_post_json", FakeTavily(dup))
    assert len(rs.web_search("KEY", "errorless")) == 1
