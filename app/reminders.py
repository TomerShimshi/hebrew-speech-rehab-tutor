"""Daily practice reminder (sub-plan 11): a notification from the app ("Web Push").

Once a day, at the account's hour (Israel time), the hourly sweep sends a short, warm
notification to every device the account turned reminders on for. Tapping it opens the app.
It's skipped when he already practised today, while the soft stop is on (10), on days not
chosen, or when there's no device -- every decision is recorded (one per day) and shown on
the caregiver page. Devices that stopped accepting notifications are removed.
"""

import datetime as dt
import hashlib
import json
import sys
from collections.abc import Callable
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app import billing_guard
from app.store import SessionStore

TZ = ZoneInfo("Asia/Jerusalem")
TITLE = "דברו איתי"
# Short, warm, adult, masculine; one per day, in turn.
TEXTS = (
    "בוקר טוב! 🌞 המטפלת מחכה לשיחה היומית שלך",
    "כמה דקות של דיבור היום? 🗣️ אני כאן",
    "השיחה היומית שלנו מחכה לך 😊",
    "מה שלומך היום? בוא נדבר קצת 🌿",
    "עוד יום, עוד שיחה. כל דקה עושה את ההבדל 💪",
)
GONE = {404, 410}  # the push service says this device's subscription no longer exists

Sender = Callable[[dict, dict], None]  # (subscription, payload) -> None; raises PushGone if gone


class PushGone(Exception):
    pass


class ReminderSettings(BaseModel):
    enabled: bool = False
    hour: int = Field(default=10, ge=0, le=23)  # Israel time
    days: list[int] = Field(default=[0, 1, 2, 3, 4, 5, 6])  # 0 = Sunday ... 6 = Saturday


def _log(message: str) -> None:
    print(f"[reminders] {message}", file=sys.stderr, flush=True)


def subscription_id(subscription: dict) -> str:
    return hashlib.sha1(subscription["endpoint"].encode("utf-8")).hexdigest()[:20]


def text_for(day: dt.date) -> str:
    return TEXTS[day.toordinal() % len(TEXTS)]


def practiced_on(store: SessionStore, pid: str, day: dt.date) -> bool:
    for s in store.list_sessions(pid, 10):
        started = s.get("started_at")
        if started and started.astimezone(TZ).date() == day and (s.get("turn_count") or 0) >= 2:
            return True
    return False


def send_to_devices(store: SessionStore, pid: str, payload: dict, sender: Sender) -> int:
    """Sends to every subscribed device; removes the ones that are gone. Returns how many got it."""
    delivered = 0
    for sub in store.list_push_subscriptions(pid):
        try:
            sender(sub, payload)
            delivered += 1
        except PushGone:
            store.remove_push_subscription(pid, sub["id"])
            _log(f"{pid}: removed a device that no longer accepts notifications")
        except Exception as exc:  # noqa: BLE001 -- one device failing mustn't stop the others
            _log(f"{pid}: a device failed: {exc!r:.150}")
    return delivered


def run_reminders(store: SessionStore, pids, sender: Sender, now: dt.datetime | None = None) -> dict:
    """Called by the hourly sweep. At most one decision per account per day."""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(TZ)
    today, weekday = now.date(), (now.weekday() + 1) % 7  # Python: Monday = 0 -> Sunday = 0
    results = {}
    for pid in pids:
        settings = ReminderSettings(**(store.get_reminder_settings(pid) or {}))
        if not settings.enabled or now.hour < settings.hour or store.get_reminder(pid, today.isoformat()):
            continue
        reason = None
        if weekday not in settings.days:
            reason = "not one of the chosen days"
        elif practiced_on(store, pid, today):
            reason = "already practised today"
        elif billing_guard.is_paused(store):
            reason = "paused (spending soft stop)"
        elif not store.list_push_subscriptions(pid):
            reason = "no device has reminders on"
        if reason:
            record = {"status": "skipped", "reason": reason}
        else:
            text = text_for(today)
            delivered = send_to_devices(store, pid, {"title": TITLE, "body": text, "url": "./"}, sender)
            record = {"status": "sent" if delivered else "failed", "text": text, "devices": delivered}
        store.save_reminder(pid, today.isoformat(), {**record, "at": now.astimezone(dt.timezone.utc)})
        _log(f"{pid}: {record['status']}" + (f" ({reason})" if reason else ""))
        results[pid] = record["status"]
    return results


def webpush_sender(private_key: str, subject: str) -> Sender:
    """The real sender (pywebpush). The private key is the raw base64url VAPID key."""
    def send(subscription: dict, payload: dict) -> None:
        from pywebpush import WebPushException, webpush  # lazy: tests use a fake sender
        try:
            webpush(subscription_info={"endpoint": subscription["endpoint"], "keys": subscription["keys"]},
                    data=json.dumps(payload, ensure_ascii=False), vapid_private_key=private_key,
                    vapid_claims={"sub": subject}, ttl=6 * 3600)
        except WebPushException as exc:
            if exc.response is not None and exc.response.status_code in GONE:
                raise PushGone() from exc
            raise
    return send
