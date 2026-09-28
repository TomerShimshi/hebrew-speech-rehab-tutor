# Sub-plan 08: Caregiver page

Part of the [master design](00-master-design.md). Depends on [07](07-web-search-subagent.md).

## Goal
Tomer (and the family) can see and manage everything without opening the Firestore console.

## Files
| File | Purpose |
|---|---|
| `static/caregiver.html`, `static/caregiver.js` | A plain HTML/JS page at `/caregiver`, in Hebrew with a right-to-left layout. |
| `app/caregiver_api.py` | `/api/caregiver/*` routes behind `require_caregiver`. |
| `app/github_issues.py` | Creates an issue on `TomerShimshi/simon` using a fine-grained token (Issues: write on that repo only) stored in Secret Manager as `GITHUB_ISSUES_TOKEN`. It **only runs when Tomer clicks the button**. The issue body is written so it can be handed straight to Claude Code. |
| `tests/` | Caregiver-only access, profile update validation, memory rollback, GitHub call against a fake HTTP client. |

## Page sections
1. **Always visible:** a banner for flags (high severity, e.g. a sudden decline), the emergency information (BE-FAST, call Magen David Adom on 101), and communication tips for the family (wait, don't finish his sentences, ask yes/no questions, write down key words).
2. **Sessions:** a list of sessions showing the summary, metrics and full transcript.
3. **Word bank:** a table of words and their progress by cue level.
4. **Profile and therapist:** edit `speech_profile`, `therapist_goals`, `avoid`, family names, interests, `language_history`, songs, VAD mode and silence length.
5. **Memory:** the current `memory_prompt`, its history, and a **rollback** to any previous version.
6. **Next plan:** view the upcoming ClassPlan.
7. **Games-app recommendations:** mark each one accepted, rejected or done, with a **"Create GitHub issue"** button.
8. **Technique notes:** saved web-search results, with their sources.

## Done when
- [ ] `pytest` passes.
- [ ] A non-caregiver account is refused.
- [ ] Profile edits change the next plan.
- [ ] Rollback restores an earlier memory version.
- [ ] A test issue is created on the Simon repo from the button.

## Commit
`Sub-plan 08: caregiver dashboard with profile editing, memory rollback and GitHub issues`
