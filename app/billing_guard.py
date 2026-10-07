"""Soft stop on spending (sub-plan 10).

The monthly budget (120 ILS) publishes its notifications to the `budget-alerts` Pub/Sub topic
several times a day, each with the month's spend so far. The kill switch (a Cloud Run function)
removes billing at 100%. This module is the gentler step before it: a push subscription sends
the same notifications to the app (POST /internal/budget), and at 75% (90 ILS) everything that
calls a model pauses -- new sessions, memory updates, plans, research, the sweep, the caregiver
page's model actions. The site, the data and the caregiver page stay up (they cost nothing).

A caregiver resumes from the caregiver page; that month isn't paused again (the kill switch
still guards 100%). A new month clears the pause by itself. Nothing is lost while paused:
ended sessions wait as "pending" and the sweep processes them after the resume.

State: Firestore usage/billing {paused, month, cost, budget, since, resumed_month, resumed_by}.
"""

import datetime as dt
import sys

from app.store import SessionStore

SOFT_STOP_RATIO = 0.75


def _log(message: str) -> None:
    print(f"[billing] {message}", file=sys.stderr, flush=True)


def _month(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m")


def handle_notification(store: SessionStore, notification: dict, now: dt.datetime | None = None) -> dict:
    """Records the month's spend; pauses at the soft-stop line (unless resumed this month)."""
    cost = float(notification.get("costAmount") or 0)
    budget = float(notification.get("budgetAmount") or 0)
    month = str(notification.get("costIntervalStart") or "")[:7] or _month(now)
    state = dict(store.get_billing_state() or {})
    if state.get("month") != month:  # a new month: start clean
        state = {"paused": False, "month": month}
    state.update(cost=cost, budget=budget, currency=notification.get("currencyCode", ""),
                 updated_at=now or dt.datetime.now(dt.timezone.utc))
    over = budget > 0 and cost >= SOFT_STOP_RATIO * budget
    if over and not state.get("paused") and state.get("resumed_month") != month:
        state.update(paused=True, since=now or dt.datetime.now(dt.timezone.utc))
        _log(f"SOFT STOP: {cost:g} of {budget:g} {state['currency']} this month -- model use paused")
    store.set_billing_state(state)
    return state


def is_paused(store: SessionStore, now: dt.datetime | None = None) -> bool:
    state = store.get_billing_state() or {}
    return bool(state.get("paused")) and state.get("month") == _month(now)


def resume(store: SessionStore, by: str, now: dt.datetime | None = None) -> dict:
    state = dict(store.get_billing_state() or {})
    month = state.get("month") or _month(now)
    state.update(paused=False, resumed_month=month, resumed_by=by, resumed_at=now or dt.datetime.now(dt.timezone.utc))
    store.set_billing_state(state)
    _log(f"resumed by {by} (cost so far {state.get('cost')} of {state.get('budget')})")
    return state
