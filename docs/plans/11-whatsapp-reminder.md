# Sub-plan 11: Daily WhatsApp reminder to practice

Part of the [master design](00-master-design.md). After [10](10-paid-gemini.md). Requested by Tomer (2026-10-07).

## Goal
Once a day, Dad gets a short, warm WhatsApp message reminding him to practice, with a link that opens the app. Daily practice matters more than long sessions (the dose research in the master design), and WhatsApp is where he already is.

## Design
- **The message:** short, warm, adult, in Hebrew, with the link. For example:
  > בוקר טוב! 🌞 המטפלת מחכה לשיחה היומית שלכם. כמה דקות של דיבור עושות את ההבדל 💪
  > https://…/
- **Variety:** a few versions rotate, so it doesn't feel automatic. Optionally, it mentions the topic of the next lesson, from the plan, in one friendly line, with no check-in answers.
- **When:** a time chosen per account (e.g. 10:00, Israel time), sent by Cloud Scheduler → the app.
- **Smart skipping:**
  - no reminder if he already practised today
  - none while the soft stop is on (10)
  - optionally, none on chosen days (e.g. Saturday)
- **Set per account on the caregiver page:** on/off, the time, the days, and the phone number. The phone number is stored in Firestore only: never in the repo, never in logs.
- **Tracked:** every reminder sent or skipped (and why) is recorded on the account and shown on the caregiver page, plus a log line.
- **Opt-in:** Dad agrees to get the messages (and WhatsApp's own rules require the recipient's opt-in for business messages).

## How to send WhatsApp messages: the options (to verify and choose before building)
| Option | What it is | Setup | Cost (to verify) | Notes |
|---|---|---|---|---|
| **WhatsApp Cloud API** (Meta, official) | A business number sends approved "template" messages | Meta Business account; a phone number for the business (not one used in the WhatsApp app); a message template approved by Meta ("utility" category) | A small per-message fee for business-initiated templates (Israel rate to check; ~30 messages a month) | The most reliable and official. The most setup. |
| **Twilio WhatsApp** | Twilio's layer over the same official API | A Twilio account (card), number + template through Twilio | Twilio's fee + Meta's | Simpler setup than Meta directly; costs a bit more |
| **CallMeBot** (free, unofficial) | A free bot service for personal notifications | The recipient (Dad's phone) sends a one-time activation message to the bot; we get a key | Free | Unofficial, for personal use; reliability not guaranteed |
| **Alternative: phone notifications** (not WhatsApp) | Web push from the home-screen app (09) | None outside the app | Free | Not WhatsApp; Android works well; iPad needs the app on the home screen |

**Recommendation, to confirm after checking current terms and prices:** the official **WhatsApp Cloud API**. The cost of ~30 messages a month is small, and it's the dependable choice for something he relies on daily. **CallMeBot** is a free option to try first, if Tomer prefers to start quickly.

## Files (expected)
| File | Purpose |
|---|---|
| `app/reminders.py` | Decide (send / skip and why), build the message, send it through the chosen provider (behind one small interface, so the provider can change). |
| `app/main.py` | `POST /internal/reminders` (Cloud Scheduler, OIDC like the sweep). |
| `app/caregiver_api.py`, `static/caregiver.*` | Reminder settings per account; history; "send a test now". |
| `deploy/setup_gcp.sh`, `.env.example` | The provider's token in Secret Manager; a scheduler job (every 15 minutes, each account's own time). |
| `tests/` | Skipped if already practised / paused / off / wrong day; message text; provider faked (never sends real messages in tests). |

## Manual steps for Tomer
- Choose the provider (after we check terms and prices together), and create the account / number / template it needs.
- Dad's phone number, entered on the caregiver page (never in the repo).
- Dad's agreement to get the messages.

## Done when
- [ ] A test message arrives on Tomer's phone from the caregiver page.
- [ ] Dad gets the daily reminder at his time, skipped when he already practised or the app is paused.
- [ ] `pytest` passes; no phone number or provider token in the repo or the logs.

## Commit
`Sub-plan 11: daily WhatsApp reminder to practice`
