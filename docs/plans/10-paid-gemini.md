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
2. **Raise the budget and kill switch first.** Today they cut everything at **4 ILS**, so the paid tier would trip them within days.
   - New budget: **80 ILS / month** (~$20), alerts by email at 50%, 90% and 100%.
   - Kill switch at **120 ILS** (only a runaway bug should hit it). Hitting it shuts down Cloud Run too: the whole app stops.
   - Both via `setup_gcp.sh` (`BUDGET_AMOUNT`), with Tomer's OK on the numbers.
3. **App-level guard against runaway use** (code): a daily cap on Live minutes per account (e.g. 60), on top of the existing 30-sessions-per-hour limit. A bug or a stuck tab can't run up a bill.
4. **Switch the key to paid** (Tomer, in AI Studio): link billing to the key's project, or create a key in `heb-practice` and put it in Secret Manager (`setup_gcp.sh` handles the secret).
5. **Model chain:** `3.8-flash` primary; keep the fallbacks for outages (503), not for quota. Log when a fallback is used.
6. **Verify:**
   - A session on Tomer's account: a plan built by `3.8-flash`, no 429s in the logs.
   - The next day: the billing report shows the day's cost per service.
   - A week later: compare with the estimate above.
7. **Docs:** README (the cost, the privacy change, how to go back to free: unlink billing / swap the key).
8. Commit and push.

## Manual steps for Tomer
- AI Studio: check the key's project and tier (step 1); later, link billing (step 4).
- Approve the budget numbers (step 2).
- Watch the budget emails during the first week.

## Done when
- [ ] The key is on the paid tier (AI Studio shows it; no more free-tier 429s).
- [ ] The budget (80 ILS) and kill switch (120 ILS) are updated, and the alert emails arrive.
- [ ] The daily Live-minutes cap works (tests).
- [ ] A week of real use costs about what was estimated.

## Commit
`Sub-plan 10: paid Gemini tier, higher budget with alerts, daily usage cap`
