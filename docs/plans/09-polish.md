# Sub-plan 09: Polish

Part of the [master design](00-master-design.md). Depends on [08](08-caregiver-page.md) / [8.5](08.5-prompt-visibility-and-grounding.md). The paid-tier switch and the cost check moved to [10](10-paid-gemini.md).

## Goal
Finishing touches that make the app better for Dad and for the people helping him. Tomer chose the items (2026-10-07). Each is built, deployed and checked on its own.

## Chosen items, in build order (small first)
1. **Cleanup + home-screen app.**
   - Delete the leftover `patient-profile` secret (the profile moved to the bucket).
   - A PWA manifest + icons. On the tablet, "Add to home screen" gives an icon that opens the app full screen, like a real app. No offline mode: the app needs the internet anyway.
2. **Model visibility.** On the caregiver page, each session shows which model ran its memory update and which built the plan after it, and the next lesson shows its model. A warning appears when the smallest fallback (`flash-lite`) was used. The data is already stored (`memory_model`, `plan_model`).
3. **Export for the therapist.** A button on the caregiver page opens a clean, printable page ("print / save as PDF"). For the chosen account it shows:
   - the date range
   - each session's summary, highlights / difficulties and check-in results
   - the check-in trend
   - the current goals and planner notes
   - the word bank's hardest words

   The text is in Hebrew where it's his words, and the summaries as stored.
4. **Progress graphs** (caregiver page, plain SVG drawn by our code, no outside libraries):
   - **Check-ins over time:** the share answered on his own (✓) per session, practised vs. new items (the progress measure from 05).
   - **Mood per session.**
   - **Word bank:** words practised so far, and how many he now gets on his own.
5. **Voice settings per account, adjusted automatically** (reworked with Tomer, 2026-10-07). Two problems pull in opposite directions, so there are two separate knobs. Each is measured from the transcript after every session, in code (no model):

   | Problem | Measured as | Knob | Rule |
   |---|---|---|---|
   | **She cuts him off** mid-thought | her turn is interrupted and his next line starts within 2.5 s of hers (he was still talking), plus `cut_off` tutor-issue reports | **silence before she answers**, 2.5–6 s (default 3) | ≥2 in a session: +0.5 s; 3 clean sessions in a row: −0.5 s |
   | **Noise interrupts her** | her turn is interrupted and he then says nothing or one word | **noise filter**, level 0–3 (default 0) | ≥2 in a session: +1; 3 clean sessions in a row: −1 |

   - **The noise filter works in the browser, only while she is speaking:** his mic passes only if the sound is loud and long enough to be speech (~0.3 s above a level threshold); otherwise silence is sent. When she's quiet everything is sent as today, so his own turns are unaffected. Level 3 also lowers Gemini's start-of-speech sensitivity. Trade-off: at higher levels, interrupting her takes a clearer voice; he can always wait for her to finish.
   - **The family keeps control:** each knob is "automatic" or a fixed value set on the caregiver page.
   - **Tap-to-talk** stays a family setting (fewer choices on his screen). The page **suggests** it when noise interruptions continue at filter level 3. On: a big "🎙️ לדבר" / "✅ סיימתי" button replaces mute; his mic is sent only during his turn; pressing "לדבר" while she talks interrupts her. (Built and deployed in the first version of this step.)
   - **Every decision is tracked:**
     - **On each session (Firestore, permanent):** the settings it ran with, what was measured, and the decision after it with its reason. Shown as a small line per session on the caregiver page.
     - **One structured JSON log line per decision** in Cloud Logging (`jsonPayload.event="voice_adjust"`), filterable in the Logs Explorer for 30 days.
   - Settings apply from the account's next session (they're baked into the session token).
6. **The target word on screen.** When she says one of the plan's answers (check-in / practice) in her speech, it appears large on his screen, with vowel marks where the plan has them, for a few seconds. Matched in the browser from her live transcript, so no tool call and no delay. On by default; it can be switched off per account (with the voice settings).
7. **Audio recordings, for the caregiver page only.**
   - **Recording:** in the browser, both voices mixed (his mic + her speech) into one Opus file (~2 MB per 12-minute session). It's uploaded when the session ends to the private bucket, under `audio/<email>/<session>.webm`, deleted automatically after **90 days**.
   - **Playing:** a "הקלטה" ("recording") button next to "תמלול מלא" ("full transcript") and "הפרומפט" ("the prompt") on each session, playing it through a caregiver-only API route. His screen shows nothing new.
   - **Cost:** about 180 MB over 90 days, within the free 5 GB.
   - **Telling Dad (Tomer: yes):** while recording is on, the start screen shows a small line "השיחות נשמרות כדי לעקוב אחרי ההתקדמות" ("sessions are saved to follow progress").
   - **Easy to turn off (Tomer: storage may grow):**
     - A per-account **"recording on / off" switch** on the caregiver page (with the voice settings). Off means no new recordings and no start-screen line; existing recordings stay until they expire.
     - The page shows the **storage used** by that account's recordings ("הקלטות: 34 קבצים, 68MB", "recordings: 34 files, 68 MB").
     - Together with the 90-day automatic deletion, the bucket can't keep growing.
   - **IAM:** the app's service account needs read access to `audio/` in the private bucket. Today it can only create objects there.

## Not chosen (kept for later)
- **Mood check-in** before each session (the memory update already estimates mood from the conversation).

## Tasks
1. [x] Cleanup + home-screen app → deploy → Tomer adds it to the tablet. Also (Tomer's requests): the app's new name **"דברו איתי"**, a "Made by Tomer Shimshi" credit on the start screen and the caregiver page, and Tomer's own image (`static/app_image.jpg`, brain + speech + tutor) as the app icon and favicon.
2. [x] Model visibility → deploy.
3. [x] Export for the therapist → deploy → Tomer tries print / save as PDF.
4. [x] **README update** (Tomer's request): what the app is, how it's built (architecture, the three agent calls, research, caregiver page), how to run it locally, deploy and set up GCP, the manual steps, costs and privacy, and links to the plan docs. No secrets or emails.
4.5. [x] **Hebrew translation of the export** (Tomer's request): pressing export asks (an inline window, "לתרגם את הסיכום לעברית?") yes / no. Yes sends the export's English texts to one model call (`prompts/translate_export.yaml`: translate only, keep his Hebrew words and names, glossary: the tutor = "המטפלת" (Tomer's choice), feminine; the patient = "המטופל"), shows the progress dots, then prints in Hebrew. On any failure it prints in English and says so.
5. [x] Progress graphs → deploy. (`GET /{email}/progress`: the numbers are computed and tested on the server, drawn as SVG on the page.)
6. [~] Voice settings, automatic (silence + noise filter, measured per session; manual override; tap-to-talk as a family setting; every decision recorded on the session and logged) → deploy → sessions on Tomer's account.
7. [ ] Target word on screen → deploy → a session.
8. [ ] Audio recordings (after Tomer's choice on telling Dad) → deploy → a session, then play it on the caregiver page.
9. [ ] Commit and push (per item or together, when Tomer says).

## Notes from building it
- **Step 6 is built and deployed; Tomer still has to try it in sessions** ([~] above):
  - tap-to-talk in a real session (does she react to the "quiet for a while" / "wrap up" notes with automatic detection off?)
  - the noise-filter thresholds (RMS 0.015 / 0.03 / 0.05 per level, 0.3 s hold) with a TV on and `?debug=1`
- **The caregiver page shows the account's voice settings at the top** (Tomer's request): each value, automatic or fixed, the last automatic decision with its reason, and the tap-to-talk suggestion, editable in place. A manual save keeps the automatic history (streaks, last decision).
- **The tutor is "המטפלת" everywhere:** the caregiver page, his captions and the image description (Tomer's choice).
- **A failed memory update on 7.10.26 exposed a retry bug** (`app/llm.py`). `3.8-flash` was overloaded (504 after hanging ~90 s, then 503). Retrying it 3× per call spent the 5-minute budget, so the working fallback (`flash-lite`) was never tried. Fixed in two steps:
  1. 503 / 504 / a client timeout → the next model at once. Per-request limit 45 s (was 90). One more pass over the chain if every model failed and time allows.
  2. An overloaded / out-of-quota model is **skipped for 10 minutes**. Otherwise every tool round of a multi-call update waits on it again: the first fix alone still ran out of time.

  After both, the stuck session processed in 63 s (memory: `3.6-flash`, plan: `flash-lite`).
- **"Process this session now" button** on unprocessed sessions (Tomer's request). It runs the same steps as the end of a session and picks up where it stopped: memory done + plan failed → only the plan (tested: one model call). It's safe to press twice (the memory update claims the session). A session still "active" after 20 minutes (tab closed) is ended as abandoned first; a newer one is refused (it may still be running).
- **Logs:** Cloud console → Logging → Logs Explorer, `resource.labels.service_name="hebrew-tutor"`. Useful filters: `textPayload:"[llm]"`, `textPayload:"[memory]"`, `jsonPayload.event="voice_adjust"`. Kept 30 days.

## Done when
- [ ] Each chosen item works on the tablet / the caregiver page.
- [ ] `pytest` passes (tests for every API route and setting; the graphs' data, not their drawing).
- [ ] Recordings play only for caregivers, and older ones are deleted after 90 days (lifecycle rule).

## Commit
Per item or together, e.g. `Sub-plan 09: progress graphs on the caregiver page`
