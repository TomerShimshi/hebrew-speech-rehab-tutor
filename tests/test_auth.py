import pytest

from conftest import auth


def test_no_token_is_401(env):
    assert env.client.post("/api/session/start").status_code == 401


def test_bad_token_is_401(env):
    assert env.client.post("/api/session/start", headers=auth("forged")).status_code == 401


def test_wrong_scheme_is_401(env):
    response = env.client.post("/api/session/start", headers={"Authorization": "Basic tok-dad"})
    assert response.status_code == 401


@pytest.mark.parametrize("token", ["tok-stranger", "tok-unverified"])
def test_not_allowed_or_unverified_is_403(env, token):
    assert env.client.post("/api/session/start", headers=auth(token)).status_code == 403


@pytest.mark.parametrize("token", ["tok-dad", "tok-tomer"])
def test_allowlisted_accounts_get_in(env, token):
    assert env.client.post("/api/session/start", headers=auth(token)).status_code == 200


def test_allowlist_is_case_insensitive(env):
    env.configure(allowed_emails=" DAD@Example.com ")
    assert env.client.post("/api/session/start", headers=auth("tok-dad")).status_code == 200
    assert env.client.post("/api/session/start", headers=auth("tok-tomer")).status_code == 403


def test_health_stays_public(env):
    assert env.client.get("/api/health").status_code == 200


def test_me_reports_allowed_account(env):
    assert env.client.get("/api/me", headers=auth("tok-dad")).json() == {"email": "dad@example.com", "is_caregiver": False, "recording": True, "paused": False,
        "reminder": {"enabled": False, "hour": 10, "days": [0, 1, 2, 3, 4, 5, 6]}}
    assert env.client.get("/api/me", headers=auth("tok-stranger")).status_code == 403
