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


def test_static_assets_are_revalidated():
    response = _client(None).get("/app.js")
    assert response.headers["cache-control"] == "no-cache"


def test_index_links_versioned_assets():
    html = _client(None).get("/").text
    assert "__ASSET_VERSION__" not in html
    assert 'href="style.css?v=' in html
    assert 'src="app.js?v=' in html


def test_home_screen_app_manifest(env):
    html = env.client.get("/").text
    assert '<link rel="manifest" href="manifest.json">' in html
    manifest = env.client.get("/manifest.json").json()
    assert manifest["display"] == "standalone" and manifest["lang"] == "he"
    assert manifest["name"] == "דברו איתי" and "<title>דברו איתי</title>" in html
    assert "Made by Tomer Shimshi" in html and "Made by Tomer Shimshi" in env.client.get("/caregiver").text
    for icon in manifest["icons"]:
        assert env.client.get(f"/{icon['src']}").status_code == 200
