from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app

SECRET = "test-secret-key-value"


def _client(key: str | None) -> TestClient:
    app.dependency_overrides[get_settings] = lambda: Settings(gemini_api_key=key)
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_health_with_key_reports_configured_without_leaking_it():
    response = _client(SECRET).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "gemini_key_configured": True}
    assert SECRET not in response.text


def test_health_without_key():
    response = _client(None).get("/api/health")
    assert response.json() == {"status": "ok", "gemini_key_configured": False}


def test_index_page_is_served_in_hebrew_rtl():
    response = _client(None).get("/")
    assert response.status_code == 200
    assert 'dir="rtl"' in response.text
    assert "שנתחיל?" in response.text
