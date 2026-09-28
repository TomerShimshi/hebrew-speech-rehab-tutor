# Sub-plan 09: Polish

Part of the [master design](00-master-design.md). Depends on [08](08-caregiver-page.md).

## Goal
Add the finishing touches from the therapist review, and run a final check that we stay on the free tier.

## Items (each small enough to commit on its own if needed)
1. **Audio recordings for the therapist.**
   - `MediaRecorder` records his mic as Opus and uploads it to a Cloud Storage bucket (us-central1, free 5 GB) with a 90-day lifecycle rule.
   - The audio location is saved on the session.
   - The caregiver page plays recordings and highlights the "review with audio" items (the ones where speech recognition was uncertain).
2. **Mood check-in.** A 1–5 faces picker before the tutor starts. The score goes into `SessionMetrics`, and several low days in a row raise a flag.
3. **Graphs on the caregiver page.**
   - probe accuracy for treated vs. untreated words
   - mood over time
   - word-bank progress
4. **Tap-to-talk mode.** Uses manual `activityStart`/`activityEnd` and can be switched on from the caregiver page.
5. **Pointed target words.** When the tutor says a ClassPlan target word, it appears in large, fully pointed Hebrew on screen (matched from the transcript, with no tool call).
6. **Home-screen app.** A PWA manifest and icon for the tablet.
7. **"Export for therapist."** A printable summary of recent sessions, metrics and observations.
8. **Free-tier check.** Review Cloud Run, Firestore, Secret Manager, Storage and Gemini usage against the free quotas, and confirm the budget alert.
9. **After the POC:** switch the Gemini key to the paid tier so Google doesn't use the data for training (about $0.20 per session). Document this in the README.

## Done when
- [ ] Each item works on the tablet.
- [ ] `pytest` passes.
- [ ] Usage stays within the free tier for a week of daily sessions.

## Commit
Per item, e.g. `Sub-plan 09: audio recordings for therapist review`
