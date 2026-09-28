# Sub-plan 02: First voice-agent draft

Part of the [master design](00-master-design.md). Depends on [01](01-gcp-skeleton.md).

## Goal
Dad (or Tomer, testing) taps **"שנתחיל?"** and holds a natural, low-latency Hebrew voice conversation with the Gemini Live native-audio model. The tutor follows a first-draft therapy prompt. There's no database or memory yet, so each session starts fresh.

## Out of scope
Login, transcript storage (03), memory (04), lesson plans (05), games (06).

## Files
| File | Purpose |
|---|---|
| `prompts/tutor.yaml` | v0 prompt, `prompt_version: 0.1`. Sections: `role`/goal, `style_rules` (slow, short sentences, one question at a time, masculine address, adult tone, never say "לא נכון" ("wrong"), never finish his sentence, no medical advice), `session_structure` (greeting → warm-up with automatic speech → simple word finding using the cueing hierarchy → short chat → end on a success with praise), `fatigue_protocol`, `safety`. It also has `{placeholders}` for later sub-plans (`memory_prompt`, `class_plan`), which render empty for now. |
| `app/prompts.py` | Loads the YAML and renders the system instruction. Missing placeholders become empty strings. |
| `app/live_token.py` | `create_live_token()` uses `google-genai` `client.auth_tokens.create` with `uses=1`, `expire_time` +30 min, `new_session_expire_time` +1 min, and `live_connect_constraints` that lock the model, the system instruction, AUDIO response, the Hebrew voice, input and output transcription, the VAD settings (low end-of-speech sensitivity, `silence_duration_ms` ≈ 4500), session resumption and context-window compression. **No tools.** |
| `app/config.py` | Adds `LIVE_MODEL` (default `gemini-3.8-live`), `LIVE_VOICE`, `VAD_SILENCE_MS`. |
| `app/main.py` | `POST /api/session/start` returns `{token, model}`. |
| `static/app.js` | Loads `@google/genai` as an ESM module from a CDN and calls `ai.live.connect` with the token (v1alpha). It streams the mic, plays the audio, shows captions, handles interruptions (clears the playback queue) and the end button. |
| `static/audio/capture-worklet.js` | Mic → downsample to 16 kHz → Int16 PCM chunks of about 40 ms. |
| `static/audio/playback-worklet.js` | A 24 kHz PCM queue with low-latency playback that can be flushed on interruption. |
| `static/index.html` / `static/style.css` | Large RTL captions (tutor vs. Dad), a listening/speaking indicator, a big **"סיום"** ("end") button, a big **"אני חושב…"** ("I'm thinking…") button that holds the turn open (briefly mutes the VAD, v0 approach), and the always-visible **emergency button**. It opens a full-screen BE-FAST message with "התקשרו למד״א 101" ("Call Magen David Adom 101"). |
| `tests/test_prompts.py`, `tests/test_live_token.py` | Tests YAML rendering, and that the token config (built with a fake genai client) contains the locked prompt, the VAD settings and no tools. |
| `requirements.txt` | Adds `google-genai`, `pyyaml`. |

## Tasks
1. Write the prompt YAML v0, then test it by hand in AI Studio's Live playground in Hebrew.
2. Backend: token endpoint and tests.
3. Frontend: the worklets and the Live connection. Test on desktop Chrome first, then on the tablet.
4. Tune the VAD silence time and voice with Tomer.
5. Deploy and try it on the tablet.

## Done when
- [ ] `pytest` passes.
- [ ] A Hebrew conversation works locally and on Cloud Run with a response latency of about 1 s or less.
- [ ] The tutor doesn't interrupt during a ~4 s pause, and interrupting the tutor stops its audio immediately.
- [ ] Captions show both sides in Hebrew.
- [ ] The API key never reaches the browser (check the DevTools network tab: only the ephemeral token appears).
- [ ] The emergency button works.

## Commit
`Sub-plan 02: Gemini Live Hebrew voice tutor v0 with ephemeral tokens`
