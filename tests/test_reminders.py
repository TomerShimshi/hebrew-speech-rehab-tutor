"""11: the daily practice reminder (a notification from the app)."""

import datetime as dt

from app import billing_guard
from app.reminders import ReminderSettings, run_reminders
from app.store import InMemorySessionStore
from conftest import DAD, TOMER, auth

SUB = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "BPk", "auth": "xyz"}}
# 7.10.2026 is a Wednesday; 10:00 in Israel = 07:00 UTC (summer time)
AT_10 = dt.datetime(2026, 10, 7, 7, 0, tzinfo=dt.timezone.utc)


def fake_sender(log):
    def send(sub, payload):
        log.append((sub["endpoint"], payload))
    return send


def setup(enabled=True, hour=10, days=(0, 1, 2, 3, 4, 5, 6), devices=1):
    store = InMemorySessionStore()
    store.save_reminder_settings(DAD, ReminderSettings(enabled=enabled, hour=hour, days=list(days)).model_dump())
    for i in range(devices):
        store.add_push_subscription(DAD, f"d{i}", {**SUB, "endpoint": SUB["endpoint"] + str(i)})
    return store


def test_sent_once_at_the_hour_with_a_rotating_text():
    store, sent = setup(), []
    assert run_reminders(store, [DAD], fake_sender(sent), AT_10 - dt.timedelta(hours=1)) == {}  # 9:00: not yet
    assert run_reminders(store, [DAD], fake_sender(sent), AT_10) == {DAD: "sent"}
    assert len(sent) == 1 and sent[0][1]["title"] == "דברו איתי" and sent[0][1]["url"] == "./"
    assert run_reminders(store, [DAD], fake_sender(sent), AT_10 + dt.timedelta(hours=1)) == {}  # once a day
    tomorrow = AT_10 + dt.timedelta(days=1)
    run_reminders(store, [DAD], fake_sender(sent), tomorrow)
    assert sent[1][1]["body"] != sent[0][1]["body"]  # a different text the next day
    record = store.get_reminder(DAD, "2026-10-07")
    assert (record["status"], record["devices"]) == ("sent", 1)


def test_a_missed_hour_still_sends_later_that_day():
    store, sent = setup(hour=8), []
    assert run_reminders(store, [DAD], fake_sender(sent), AT_10) == {DAD: "sent"}  # 8:00 sweep missed


def test_skipped_and_why():
    store, sent = setup(days=(0, 1, 2, 4, 5, 6)), []  # not Wednesday
    run_reminders(store, [DAD], fake_sender(sent), AT_10)
    assert store.get_reminder(DAD, "2026-10-07")["reason"] == "not one of the chosen days"

    store = setup()
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    store.update_session(DAD, sid, {"started_at": AT_10 - dt.timedelta(hours=2), "turn_count": 12})
    run_reminders(store, [DAD], fake_sender(sent), AT_10)
    assert store.get_reminder(DAD, "2026-10-07")["reason"] == "already practised today"

    store = setup()
    billing_guard.handle_notification(store, {"costAmount": 100, "budgetAmount": 120,
                                              "costIntervalStart": "2026-10-01T07:00:00Z"}, AT_10)
    run_reminders(store, [DAD], fake_sender(sent), AT_10)
    assert store.get_reminder(DAD, "2026-10-07")["reason"] == "paused (spending soft stop)"

    store = setup(devices=0)
    run_reminders(store, [DAD], fake_sender(sent), AT_10)
    assert store.get_reminder(DAD, "2026-10-07")["reason"] == "no device has reminders on"
    assert sent == []

    store = setup(enabled=False)
    assert run_reminders(store, [DAD], fake_sender(sent), AT_10) == {} and store.list_reminders(DAD) == []


def test_subscribe_send_and_dead_devices_are_removed(env):
    r = env.client.post("/api/push/subscribe", headers=auth("tok-dad"), json={"subscription": SUB})
    assert r.status_code == 200
    gone = {**SUB, "endpoint": "https://fcm.googleapis.com/fcm/send/gone"}
    env.client.post("/api/push/subscribe", headers=auth("tok-dad"), json={"subscription": gone})
    env.client.post("/api/push/subscribe", headers=auth("tok-dad"), json={"subscription": SUB})  # same device again
    assert len(env.store.list_push_subscriptions(DAD)) == 2
    assert env.client.post("/api/push/subscribe", headers=auth("tok-dad"),
                           json={"subscription": {"endpoint": "http://evil", "keys": {}}}).status_code == 422
    # the caregiver turns it on and sends a test
    body = {"reminder": {"enabled": True, "hour": 10, "days": [0, 1, 2, 3, 4, 5, 6, 9]}}
    assert env.client.put(f"/api/caregiver/{DAD}/reminder", headers=auth("tok-tomer"), json=body).status_code == 200
    assert env.store.get_reminder_settings(DAD)["days"] == [0, 1, 2, 3, 4, 5, 6]  # nonsense day dropped
    assert env.client.post(f"/api/caregiver/{DAD}/reminder/test", headers=auth("tok-tomer")).json() == {"devices": 1}
    assert env.pushed[0][0] == SUB["endpoint"] and "(בדיקה)" in env.pushed[0][1]["body"]
    assert len(env.store.list_push_subscriptions(DAD)) == 1  # the gone device was removed
    ov = env.client.get(f"/api/caregiver/{DAD}/overview", headers=auth("tok-tomer")).json()["reminder"]
    assert ov["enabled"] is True and ov["devices"] == 1 and ov["history"][0]["status"] == "test"
    assert env.client.put(f"/api/caregiver/{DAD}/reminder", headers=auth("tok-dad"), json=body).status_code == 403
    assert env.client.post(f"/api/caregiver/{TOMER}/reminder/test", headers=auth("tok-tomer")).json() == {"devices": 0}


def test_the_hourly_sweep_sends_them(env):
    env.client.post("/api/push/subscribe", headers=auth("tok-dad"), json={"subscription": SUB})
    env.store.save_reminder_settings(DAD, {"enabled": True, "hour": 0, "days": [0, 1, 2, 3, 4, 5, 6]})
    body = env.client.post("/internal/memory/sweep", headers={"Authorization": "Bearer oidc-scheduler"}).json()
    assert body["reminders"] == {DAD: "sent"} and len(env.pushed) == 1



def test_he_turns_it_on_and_picks_the_hour_himself(env):
    me = env.client.get("/api/me", headers=auth("tok-dad")).json()["reminder"]
    assert me == {"enabled": False, "hour": 10, "days": [0, 1, 2, 3, 4, 5, 6]}
    env.store.save_reminder_settings(DAD, {"enabled": False, "hour": 10, "days": [0, 1, 2, 3, 4]})  # caregiver's days
    r = env.client.put("/api/reminder", headers=auth("tok-dad"), json={"enabled": True, "hour": 17})
    assert r.json() == {"enabled": True, "hour": 17, "days": [0, 1, 2, 3, 4]}  # his hour, the caregiver's days kept
    assert env.client.put("/api/reminder", headers=auth("tok-dad"), json={"enabled": False}).json()["hour"] == 17
    assert env.client.put("/api/reminder", headers=auth("tok-dad"), json={"enabled": True, "hour": 25}).status_code == 422
    assert env.store.get_reminder_settings(TOMER) is None  # only his own account
    caregiver_view = env.client.get(f"/api/caregiver/{DAD}/overview", headers=auth("tok-tomer")).json()["reminder"]
    assert (caregiver_view["enabled"], caregiver_view["hour"]) == (False, 17)
