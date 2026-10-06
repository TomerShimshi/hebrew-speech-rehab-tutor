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
5. **Voice settings per account** (caregiver page → saved in Firestore → used when that account starts a session):
   - **Silence before she answers:** 2–8 seconds (today 3 for everyone).
   - **Tap-to-talk:** instead of automatic detection, he taps "דבר" ("speak") to start and "סיימתי" ("I'm done") when finished (Gemini's manual activity start/end). For noisy rooms, or if she cuts him off.

   The session token is built per account, so the settings apply from his next session.
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
5. [ ] Progress graphs → deploy.
6. [ ] Voice settings (silence + tap-to-talk) → deploy → a session with each setting.
7. [ ] Target word on screen → deploy → a session.
8. [ ] Audio recordings (after Tomer's choice on telling Dad) → deploy → a session, then play it on the caregiver page.
9. [ ] Commit and push (per item or together, when Tomer says).

## Done when
- [ ] Each chosen item works on the tablet / the caregiver page.
- [ ] `pytest` passes (tests for every API route and setting; the graphs' data, not their drawing).
- [ ] Recordings play only for caregivers, and older ones are deleted after 90 days (lifecycle rule).

## Commit
Per item or together, e.g. `Sub-plan 09: progress graphs on the caregiver page`
