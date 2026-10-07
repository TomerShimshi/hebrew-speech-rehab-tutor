"""10: the soft stop on spending (75% of the budget) and resuming it."""

import base64
import datetime as dt
import json

from app import billing_guard
from app.store import InMemorySessionStore
from conftest import DAD, TOMER, auth

NOW = dt.datetime.now(dt.timezone.utc)
MONTH = NOW.strftime("%Y-%m")


def push(env, cost, budget=120, token="oidc-scheduler", month=MONTH):
    note = {"costAmount": cost, "budgetAmount": budget, "currencyCode": "ILS",
            "costIntervalStart": f"{month}-01T07:00:00Z", "budgetDisplayName": "hebrew-tutor-budget"}
    body = {"message": {"data": base64.b64encode(json.dumps(note).encode()).decode()}, "subscription": "s"}
    return env.client.post("/internal/budget", headers={"Authorization": f"Bearer {token}"}, json=body)


def test_below_the_line_nothing_pauses(env):
    assert push(env, 89.9).json() == {"ok": True, "paused": False}
    assert env.client.get("/api/me", headers=auth("tok-dad")).json()["paused"] is False


def test_at_75_percent_model_use_pauses_and_the_site_stays_up(env):
    assert push(env, 90).json()["paused"] is True
    assert env.client.get("/api/me", headers=auth("tok-dad")).json()["paused"] is True  # his screen says so
    r = env.client.post("/api/session/start", headers=auth("tok-dad"))
    assert (r.status_code, r.json()["detail"]) == (503, "paused")
    for path in (f"/api/caregiver/{DAD}/plan/rebuild", f"/api/caregiver/{DAD}/export/translate"):
        assert env.client.post(path, headers=auth("tok-tomer"), json={"texts": ["x"]}).status_code == 409
    assert env.client.get(f"/api/caregiver/{DAD}/overview", headers=auth("tok-tomer")).status_code == 200  # page works
    assert env.client.post("/internal/memory/sweep",
                           headers={"Authorization": "Bearer oidc-scheduler"}).json()["paused"] is True
    banner = env.client.get("/api/caregiver/accounts", headers=auth("tok-tomer")).json()["billing"]
    assert banner["paused"] is True and banner["cost"] == 90 and banner["budget"] == 120


def test_a_session_ending_while_paused_waits_for_the_sweep(env):
    sid = env.client.post("/api/session/start", headers=auth("tok-dad")).json()["session_id"]
    push(env, 95)
    body = env.client.post(f"/api/session/{sid}/end", headers=auth("tok-dad"), json={"reason": "end_button"}).json()
    assert body["paused"] is True and env.store.get_session(DAD, sid)["memory_status"] == "pending"


def test_resume_lasts_for_the_rest_of_the_month(env):
    push(env, 92)
    assert env.client.post("/api/caregiver/billing/resume", headers=auth("tok-dad")).status_code == 403
    assert env.client.post("/api/caregiver/billing/resume", headers=auth("tok-tomer")).status_code == 200
    assert env.client.get("/api/me", headers=auth("tok-dad")).json()["paused"] is False
    assert push(env, 110).json()["paused"] is False  # later notifications this month don't pause again
    assert env.client.post("/api/session/start", headers=auth("tok-dad")).status_code == 200
    state = env.store.get_billing_state()
    assert (state["resumed_by"], state["cost"]) == (TOMER, 110)


def test_a_new_month_starts_clean():
    store = InMemorySessionStore()
    billing_guard.handle_notification(store, {"costAmount": 100, "budgetAmount": 120,
                                              "costIntervalStart": "2026-09-01T07:00:00Z"})
    assert store.get_billing_state()["paused"] is True
    october = dt.datetime(2026, 10, 2, tzinfo=dt.timezone.utc)
    assert billing_guard.is_paused(store, october) is False  # September's pause doesn't carry over
    billing_guard.handle_notification(store, {"costAmount": 3, "budgetAmount": 120,
                                              "costIntervalStart": "2026-10-01T07:00:00Z"}, october)
    assert store.get_billing_state()["paused"] is False and store.get_billing_state()["month"] == "2026-10"


def test_only_the_signed_pubsub_push_is_accepted(env):
    assert push(env, 100, token="oidc-other").status_code == 403
    assert env.client.post("/internal/budget", json={}).status_code == 401
    assert env.client.post("/internal/budget", headers={"Authorization": "Bearer oidc-scheduler"},
                           json={"message": {"data": "not base64 json"}}).json() == {"ok": False}



# ---- runaway guards on paid use (10) ---------------------------------------------------------------

def test_daily_live_minutes_cap(env, monkeypatch):
    import app.main
    noon = dt.datetime.now(dt.timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)  # 12:00 in Israel
    monkeypatch.setattr(app.main, "now_utc", lambda: noon)  # never flaky near midnight
    env.configure(live_daily_minutes=60, live_max_session_minutes=30)
    for minutes in (25, 25):  # two long sessions today
        sid = env.client.post("/api/session/start", headers=auth("tok-dad")).json()["session_id"]
        started = noon - dt.timedelta(minutes=minutes + 1)
        env.store.update_session(DAD, sid, {"started_at": started, "status": "ended",
                                            "ended_at": started + dt.timedelta(minutes=minutes)})
    third = env.client.post("/api/session/start", headers=auth("tok-dad"))
    assert third.status_code == 200  # 50 < 60
    sid = third.json()["session_id"]  # that one ran 15 minutes
    started = noon - dt.timedelta(minutes=16)
    env.store.update_session(DAD, sid, {"started_at": started, "status": "ended",
                                        "ended_at": started + dt.timedelta(minutes=15)})
    r = env.client.post("/api/session/start", headers=auth("tok-dad"))
    assert (r.status_code, r.json()["detail"]) == (429, "daily_limit")  # 65 >= 60
    assert env.client.post("/api/session/start", headers=auth("tok-tomer")).status_code == 200  # per account


def test_a_session_left_open_cannot_reconnect_forever(env):
    env.configure(live_max_session_minutes=30)
    sid = env.client.post("/api/session/start", headers=auth("tok-dad")).json()["session_id"]
    ok = env.client.post("/api/session/start", headers=auth("tok-dad"), json={"session_id": sid})
    assert ok.status_code == 200  # a normal reconnect
    env.store.update_session(DAD, sid, {"started_at": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=31)})
    r = env.client.post("/api/session/start", headers=auth("tok-dad"), json={"session_id": sid})
    assert (r.status_code, r.json()["detail"]) == (409, "session_too_long")
