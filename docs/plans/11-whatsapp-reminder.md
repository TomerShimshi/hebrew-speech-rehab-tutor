# Sub-plan 11: Daily reminder to practice (app notification)

Part of the [master design](00-master-design.md). After [10](10-paid-gemini.md). Requested by Tomer (2026-10-07).

## Goal
Once a day, Dad gets a short, warm notification on his phone / tablet reminding him to practice. Tapping it opens the app. Daily practice matters more than long sessions (the dose research in the master design).

## Why a notification from the app, not WhatsApp (decided with Tomer, 2026-10-07)
- **WhatsApp:**
  - Meta's official business API charges per message.
  - CallMeBot is free, but unofficial, and the messages come from a foreign bot number.
  - Automating a personal WhatsApp number breaks WhatsApp's terms and risks a ban.
- **SMS** costs per message.
- **A notification from the home-screen app (09)** is **free**, needs **no outside service**, and is standard on the web ("Web Push").
  - **Android:** it works in Chrome.
  - **iPhone / iPad:** it works only when the app is added to the home screen (iOS 16.4+), which is what we recommend anyway.
- The file name keeps "whatsapp" from the first draft; the plan is notifications.

## Design
- **Turning it on (once per device, on his screen):**
  - A button on the start screen, **"🔔 תזכורת יומית"** ("daily reminder"), shown only while that device isn't subscribed.
  - Pressing it asks the browser's permission ("דברו איתי wants to send notifications" → Allow). The device then subscribes, and the server stores the subscription under his account.
  - Browsers only allow this after a tap, so it can't be done for him silently; Tomer can do it with him on his device.
- **The message:**
  - Short, warm, adult Hebrew, masculine. A few versions rotate: "בוקר טוב! 🌞 המטפלת מחכה לשיחה היומית שלך", "כמה דקות של דיבור היום? 🗣️ אני כאן", …
  - Title: "דברו איתי", with the app icon.
  - Tapping it opens the app.
- **When:**
  - At the account's chosen **hour** (Israel time, e.g. 10:00).
  - Sent by the existing **hourly sweep** (Cloud Scheduler), so there's no new job: it runs on the hour, and a reminder set for 10:00 goes out at 10:00.
- **Smart skipping**, each recorded with the reason:
  - he already practised today
  - the soft stop is on (10)
  - today isn't one of the chosen days
  - it was already sent today
- **On the caregiver page, per account** (with the other settings at the top):
  - on/off, the hour, the days
  - how many devices are subscribed
  - the last reminders sent or skipped, and why
  - **"שליחת תזכורת לבדיקה"** ("send a test reminder"): sends one now to that account's devices
- **Subscriptions that stop working** (app removed, permission revoked) are removed automatically. Push services answer "gone" for those.
- **Keys:**
  - Web Push needs one "VAPID" key pair, generated once.
  - The private key goes in Secret Manager; the public key is not secret.
  - Free; no account anywhere.

## Files
| File | Purpose |
|---|---|
| `static/sw.js` | The service worker: shows the notification, and opens the app on tap. |
| `static/app.js`, `static/index.html` | The "🔔 תזכורת יומית" button; subscribe and send the subscription to the server. |
| `app/reminders.py` | Decide (send / skip and why), the rotating texts, send through Web Push (`pywebpush`), remove dead subscriptions. |
| `app/main.py` | `POST /api/push/subscribe`, `GET /api/push/public-key`; reminders in the hourly sweep. |
| `app/caregiver_api.py`, `static/caregiver.*` | Reminder settings, devices, history, "send a test". |
| `app/store.py` | Subscriptions + reminder history per account. |
| `deploy/*`, `requirements.txt` | The VAPID private key in Secret Manager; `pywebpush`. |
| `tests/` | Send / skip rules (practised, paused, day, already sent, hour), subscribe, dead subscriptions removed, caregivers only; Web Push faked (tests never send). |

## Progress (2026-10-07)
- Built and deployed (revision 56): `app/reminders.py` (send / skip rules, rotating texts, `pywebpush`, gone devices removed), `static/sw.js`, the "🔔 תזכורת יומית" button, `POST /api/push/subscribe`, reminders inside the hourly sweep (before the soft-stop check, so a paused day is recorded as skipped), caregiver settings / devices / last reminder / "send a test".
- Keys: VAPID pair generated once; public key in `.env` + an env var, private key in Secret Manager (`vapid-private-key`). Tests blank both and use a fake sender.
- A missed hour still sends later that day (the condition is "the hour has come", not "exactly this hour").
- **Tomer's feedback, built (revision 57):**
  - **The start screen always shows the reminder.** When it's on: "🔔 תזכורת יומית כל יום ב־10:00 · שינוי"; when it's off: "🔕 התזכורת כבויה · להפעיל"; on a device that isn't subscribed: the button.
  - **He can pick the hour himself:** big buttons 08 / 10 / 13 / 17 / 19 and "turn off" (`PUT /api/reminder`, his own account only; the caregiver's chosen days are kept). The caregiver page still sets any hour and the days, so the family decides whether to leave it to him.
  - **Turning it on from his screen does both steps:** it subscribes the device **and** switches the reminder on for the account. Before, only the device was subscribed, so nothing showed and nothing was sent until the caregiver page switched it on.
- Tomer checked it on his account (7.10.26). Still open: a real daily reminder on Dad's S24.

## Manual steps for Tomer
- On Dad's phone / tablet: open the app from the **home-screen icon**, press "🔔 תזכורת יומית" and **Allow**.
- Choose the hour and days on the caregiver page, and send a test.

## Done when
- [x] Tomer turned it on from his device and checked the reminder line (7.10.26).
- [ ] Dad gets the daily reminder at his hour, and it's skipped when he already practised or the app is paused.
- [x] `pytest` passes.

## Commit
`Sub-plan 11: daily practice reminder as an app notification`
