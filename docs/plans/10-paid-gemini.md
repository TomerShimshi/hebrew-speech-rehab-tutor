# Sub-plan 10: Switch to the paid Gemini tier

Part of the [master design](00-master-design.md). After [09](09-polish.md). Requested by Tomer (2026-10-07).

## Why
- **Privacy:** on the free tier, Google may use the conversations (his voice and health details) to improve its products; on the paid tier it doesn't ([pricing page](https://ai.google.dev/gemini-api/docs/pricing)). This was always the plan once the POC worked.
- **Quality:** the free daily quota of the stronger models keeps running out. Plans and memory updates then fall back to `3.5-flash-lite`, the model behind the invented-names problem (8.5) and weaker Hebrew. On the paid tier `3.8-flash` handles them every time.
- **Search:** the paid tier includes 5,000 Google-grounded searches a month. This is optional; Tavily (07) keeps working.

## Expected cost (prices checked 2026-10-06)
| Per daily ~12-minute session | Estimate |
|---|---|
| Live voice: audio in $0.005/min × 12 + audio out $0.018/min × ~6 | ≈ $0.17 |
| Live text context (the ~8k-token prompt): once ≈ $0.01, or re-charged every turn ≈ $0.12+ (the page doesn't say) | $0.01–0.25 |
| Memory update + plan builder on `3.8-flash` ($0.75 / $3.75 per 1M tokens) | ≈ $0.08 |
| **Per session** | **≈ $0.25–0.50** |

**Per month:** about **$8–15** with a daily session for Dad, plus test sessions. **From 1 January 2027** `3.8-flash` doubles in price: about +$2–3 a month. GCP itself and Tavily stay free at this volume.

## Steps
1. **Find out where the key's tier comes from.** The `heb-practice` project already has a billing account (for Cloud Run), yet the key behaves as free tier. So, in AI Studio → API keys / Billing:
   - Which project does the key belong to?
   - What tier does AI Studio show?
   - What does "set up billing / upgrade" link?

   Tomer does this with me (screenshots are enough). No changes yet.
2. **Raise the budget, add a soft stop, keep the kill switch** (numbers approved by Tomer, 2026-10-07). Today everything stops at **4 ILS**, so the paid tier would trip it within days. One monthly budget of **120 ILS**, with three thresholds:

   | Spend | What happens |
   |---|---|
   | **60 ILS** (50%) | email to Tomer |
   | **90 ILS** (75%) | **soft stop**, automatic: new sessions and background model calls are paused; the site, the data and the caregiver page stay up (free); his screen shows "האימון מושהה כרגע, נחזור בקרוב"; the caregiver page shows a banner with a **"resume"** button |
   | **120 ILS** (100%) | **kill switch** (as today): billing is removed from the project and the whole app stops; only a runaway bug should get here |

   - **How the soft stop works:** the budget already publishes to the `budget-alerts` Pub/Sub topic (that's how the kill switch works). A second, push subscription sends the same message to the app (`POST /internal/budget`, OIDC-verified like the hourly sweep). At ≥ 90 ILS the app sets a Firestore flag `usage/billing {paused: true, since, cost}`, and every model-calling path checks it: session start, memory update, plan builder, research, the sweep, rebuild / process. Refused calls are recorded, not lost: they wait for the sweep after "resume".
   - **Resume** (caregiver page, caregivers only) clears the flag. The budget emails keep coming; a new month starts the budget from zero, and the flag clears by itself when the month changes.
   - **Manual options** stay available at any time (documented in the README): disable the Generative Language API (stops Gemini only), or remove billing from the project (stops everything).
   - Budget emails lag real usage by a few hours, so spend can pass a threshold a little before anything reacts.
   - Set up through `setup_gcp.sh` (`BUDGET_AMOUNT=120`, the thresholds, the push subscription).
3. **App-level guard against runaway use** (code): a daily cap on Live minutes per account (e.g. 60), on top of the existing 30-sessions-per-hour limit. A bug or a stuck tab can't run up a bill.
4. **Switch the key to paid** (Tomer, in AI Studio): link billing to the key's project, or create a key in `heb-practice` and put it in Secret Manager (`setup_gcp.sh` handles the secret).
5. **Model chain:** `3.8-flash` primary; keep the fallbacks for outages (503), not for quota. Log when a fallback is used.
6. **Search fallback: Gemini's Google Search once Tavily runs out** (Tomer's request).
   - Research (07) keeps **Tavily first** (free 1,000 / month).
   - When Tavily is unavailable (our 800 / month counter reached, Tavily's quota error, no key), the same `web_search` tool falls back to **Gemini with Google Search grounding**. The paid tier includes 5,000 grounded searches a month (shared across 3.x models), then $14 per 1,000.
   - **Its own monthly counter** (e.g. 1,000) keeps it well inside the free 5,000.
   - **How it fits:** grounding can't be combined with function calling in one request, so the fallback is a separate call inside the tool handler. Gemini searches, and our code takes the sources from the response's grounding metadata (title, URL, snippet).
   - **The same guardrails apply:** only sources returned in this run are kept, the medical blocklist, no personal data in queries, and trusted-domain marking. Grounding can't be limited to chosen sites, so "trusted" searches add `site:` terms for the trusted domains, and results are marked by their real domain.
   - **To check when building:** the grounding URLs are Google redirect links (`vertexaisearch.cloud.google.com/grounding-api-redirect/...`). The real URL must be resolved (follow the redirect) before checking the domain and saving the source.
   - **On the free tier** this fallback gets 429 (no grounding quota): research is skipped, as today. So it only works after the switch.
7. **Verify:**
   - A session on Tomer's account: a plan built by `3.8-flash`, no 429s in the logs.
   - The next day: the billing report shows the day's cost per service.
   - A week later: compare with the estimate above.
8. **Docs:** README (the cost, the privacy change, how to go back to free: unlink billing / swap the key).
9. [x] Commit and push (the one-week cost check stays open).

## Progress (2026-10-07)
- **Step 1, done:** the old key belonged to **"Gemini Heb Project"** (`gen-lang-client-0738753000`), a project AI Studio created, with no billing: that's why it stayed on the free tier although `heb-practice` had billing. Billing account: "My Billing Account 1" (the only open one; Tomer added 60 ILS credit, which is on the billing account, not on a project).
- **Chosen (Tomer): option 2, one project for everything.**
  1. Budget raised to **120 ILS** on `heb-practice`, thresholds 50 / 75 / 100% (`setup_gcp.sh` defaults updated). The kill switch fires at 100%. **The soft stop at 75% isn't built yet**: until then, 90 ILS sends only an email.
  2. Generative Language API enabled on `heb-practice`. Tomer created a new key there in AI Studio ("Import project" → `heb-practice`).
  3. The new key is secret version 2; version 1 (the old key) is disabled; deployed. Checked: paid tier (Google Search grounding works), `3.8-flash` answers.
  4. Billing **removed** from "Gemini Heb Project": the old key is back on the free tier and unused. Tomer to delete it in AI Studio.
- **Soft stop, built and deployed** (revision 53):
  - `app/billing_guard.py`; `POST /internal/budget` (Pub/Sub push, signed as the sweeper's service account, verified like the sweep); state in Firestore `usage/billing`.
  - At ≥ 75% of the budget, session start returns 503 "paused" (his screen: "האימון מושהה כרגע, נחזור בקרוב 🙏", start button disabled). /end saves the transcript and leaves the memory update "pending". The sweep does nothing. The caregiver page's model actions (rebuild, process, translate, remove a memory item) return 409.
  - The caregiver page shows a red banner with the spend and **"▶️ להמשיך (לשאר החודש)"**; once resumed, that month isn't paused again. A new month clears the pause.
  - GCP: push subscription `budget-to-app` (budget-alerts → /internal/budget), plus the Pub/Sub service agent may sign tokens as the sweeper's service account. In `setup_gcp.sh` too.
  - **End-to-end test with a fake low-spend message** (10 of 120 ILS): the app recorded it without pausing, and the kill switch logged "cost 10 < budget 120: nothing to do". 6 tests cover the rest (pause, resume, new month, the guards, signed pushes only).
- **Still to build:** the daily live-minutes cap (step 3), the Gemini search fallback (step 6), the docs (step 8).

## Manual steps for Tomer
- AI Studio: check the key's project and tier (step 1); later, link billing (step 4).
- ~~Approve the budget numbers (step 2)~~: done (soft stop 90 ILS, kill switch 120 ILS).
- Watch the budget emails during the first week.

## Done when
- [x] The key is on the paid tier (AI Studio shows it; no more free-tier 429s).
- [~] The budget (120 ILS: email at 60, soft stop at 90, kill switch at 120) is set; the alert emails will show with real spend.
- [x] The soft stop pauses model use and "resume" restarts it (tests + a dry-run Pub/Sub message).
- [x] The daily Live-minutes cap works (tests).
- [x] With Tavily unavailable, research falls back to Gemini search, with the same guardrails (tests; one live run).
- [ ] A week of real use costs about what was estimated.

## Commit
`Sub-plan 10: paid Gemini tier, higher budget with alerts, daily usage cap, Gemini search fallback`
