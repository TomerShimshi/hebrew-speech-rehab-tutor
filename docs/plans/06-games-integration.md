# Sub-plan 06: Games-app integration + session refresh (call #1)

Part of the [master design](00-master-design.md). Depends on [05](05-next-class-builder.md).

## Goal
The agent reads Dad's progress in the Simon games app **without assuming a fixed set of games**, so new games are picked up automatically. The tutor gives game homework based on real results, and the agent writes recommendations for changing the games app. Adds call #1, which refreshes the plan at session start only when needed.

## Out of scope
Changing the Simon repo. Recommendations are only stored here; the GitHub button comes in 08.

## Files
| File | Purpose |
|---|---|
| `app/games.py` | A read-only Upstash REST client that follows the tolerant pattern in `../simon/src/simon/kv_store.py`. **Game discovery:** the Upstash key `games_catalog_v1` if present → otherwise `prompts/games_catalog.yaml` + `SCAN` for `*progress*` keys. `trends(sessions)` reports count, last played, how often he plays, and best/average of the numeric fields, all computed generically. |
| `prompts/games_catalog.yaml` | A fallback description of the current games (simon, memory, subword): skills trained, progress key, adjustable settings, URL. |
| `app/agent/tools.py` | Adds `list_games()`, `read_game_progress(key, n)`, `add_games_app_recommendation(...)`. |
| `app/schemas.py` | `GamesAppRecommendation{game_id, kind: tune_difficulty\|bug\|ux\|new_game\|platform, title, rationale, evidence, suggested_change, priority}`. Dedupe key: `game_id+kind+title`. |
| `app/agent/refresh.py` | Call #1. `needs_refresh()` is **deterministic**: true if there is no `next_plan`, new game sessions since the plan was made, a profile or therapist edit, ≥3 days since the last session, or a baseline session. Only then does the LLM refresh the ClassPlan. |
| `prompts/session_refresh.yaml` | Instructions for call #1. |
| `prompts/next_class.yaml` | Adds: link games to therapy goals, file recommendations (including "platform" items such as publishing `games_catalog_v1`), and never change difficulty based on speech transcripts alone. |
| `app/main.py` | `/api/session/prepare` runs `needs_refresh` and call #1 if needed. It shows "מכין את השיעור…" ("preparing the lesson…"). |
| Secrets | `UPSTASH_REDIS_REST_URL` and a **read-only** `UPSTASH_REDIS_REST_TOKEN` in Secret Manager, mounted via `deploy.sh`. |
| `tests/` | Fake Upstash: discovery with and without a catalog, an unknown progress key, trends, each `needs_refresh` trigger, recommendation dedupe. |

## Manual steps for Tomer
Copy the read-only REST token from the Upstash console into Secret Manager (`setup_gcp.sh` will prompt for it).

## Done when
- [ ] `pytest` passes.
- [ ] After playing a Simon game, opening the tutor triggers a refresh, and the tutor mentions the real result.
- [ ] Homework names a specific game with a reason.
- [ ] Recommendations appear in `games_app_recommendations` without duplicates.

## Commit
`Sub-plan 06: generic games-app progress reader, session refresh and games-app recommendations`
