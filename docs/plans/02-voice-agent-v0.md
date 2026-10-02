# Sub-plan 02: First voice-agent draft

Part of the [master design](00-master-design.md). Depends on [01](01-gcp-skeleton.md) (done: Cloud Run + Secret Manager + kill switch).

## Goal
Dad (or Tomer, testing) taps **"שנתחיל?"** and holds a natural, low-latency Hebrew voice conversation with the Gemini Live native-audio model. The tutor follows a first-draft therapy prompt. There's no database, memory or login yet, so each session starts fresh.

## Out of scope
- login and transcript storage (03)
- memory (04)
- lesson plans (05)
- games (06)
- audio recording and tap-to-talk mode (09)

## Design decisions (updated after 01 and a check of the Live API docs, 2026-09-29)
- **No JS SDK. The browser opens a raw WebSocket** to the endpoint for ephemeral tokens: `wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained?access_token=<token>`. That avoids a CDN dependency and a build step. The protocol is small: a `setup` message, `realtimeInput.audio` chunks (`audio/pcm;rate=16000`), and `serverContent` messages carrying `modelTurn.parts[].inlineData` (24 kHz PCM), `inputTranscription`, `outputTranscription`, `interrupted`, `turnComplete`, `goAway` and `sessionResumptionUpdate`.
- **The backend locks the whole config into the token.** `google-genai` → `client.auth_tokens.create(config={uses: 1, expire_time, new_session_expire_time, live_connect_constraints: {model, config: {...}}})`, which the browser uses as `token.name`. The locked config covers the model, the system instruction, AUDIO response, the voice, input and output transcription, the VAD settings, session resumption and context-window compression. **No tools.** The browser's `setup` message only names the model, so it can't change the prompt.
- **Models come from config, not code.** `LIVE_MODEL` defaults to `gemini-3.8-live`, the current name in the docs.
- **The API lives under `/api/*`.** Lesson from 01: Cloud Run reserves paths ending in `z`.
- **Protecting the quota before login exists (03).** The URL is public until then. The Gemini key is on the free tier with no billing, so abuse **can't cost money**; it can only use up the free quota. v0 adds a simple in-memory limit on token minting (e.g. 30 per hour). That works because `max-instances 1` means a single process.
- **Audio in the browser**
  - The mic is captured with an `AudioWorklet` at the device's own sample rate (iPad and Android tablets use 44.1 or 48 kHz). The worklet downsamples to 16 kHz Int16 and sends chunks of about 40 ms, base64-encoded over the WebSocket.
  - Playback runs in a second `AudioWorklet` with a 24 kHz queue. On `interrupted` it **flushes immediately**, so Dad can talk over the tutor.
  - Echo cancellation, noise suppression and auto-gain are on (`getUserMedia` constraints), so the tutor doesn't hear itself on a tablet speaker.
- **Microphone access needs HTTPS.** Cloud Run provides it, and localhost is allowed.
- **VAD (voice detection) tuned for slow speech.** End-of-speech sensitivity is LOW and `silence_duration_ms` is about 4500 (configurable). The **"אני חושב…"** ("I'm thinking…") button sends `activityStart` / pauses the end-of-speech detection for up to about 15 s, so the tutor waits. The exact approach will be settled during implementation; the fallback is a prompt instruction plus the longer silence setting.
- **Sessions are 10–12 min**, under the 15-min limit for audio sessions. The client handles `goAway` with session resumption, reconnecting with a fresh token and the resumption handle.

## Files
| File | Purpose |
|---|---|
| `prompts/tutor.yaml` | v0 prompt, `prompt_version: 0.1`, written in Hebrew with English section keys. Sections: `role` and goal; `style_rules` (slow, short sentences, one question at a time, masculine address, adult tone, never "לא נכון" ("wrong"), never finish his sentence, wait patiently, no medical advice); `session_structure` (warm greeting → warm-up with automatic speech such as counting or days of the week → simple word finding using the cueing hierarchy: semantic → first syllable → sentence completion → model and repeat → short chat about his interests → end on a success with praise); `fatigue_protocol`; `safety` (sudden worsening or distress → gently stop, suggest calling family or 101). Empty placeholders `{memory_prompt}` and `{class_plan}` for later sub-plans. |
| `app/prompts.py` | Loads the YAML and renders the system instruction. Missing placeholders become empty strings. Exposes `prompt_version`. |
| `app/live_token.py` | `create_live_token(settings, client)` builds the locked config and returns `{token, model, expires_at}`. The genai client is injected so tests can use a fake. |
| `app/rate_limit.py` | A tiny in-memory sliding-window limiter for token minting. |
| `app/config.py` | Adds `LIVE_MODEL`, `LIVE_VOICE` (Hebrew-capable voice, default to be picked while testing), `VAD_SILENCE_MS=4500`, `TOKEN_RATE_LIMIT_PER_HOUR=30`. |
| `app/main.py` | `POST /api/session/start` returns `{token, model, ws_url}`. It returns 503 if the key is missing and 429 if the rate limit is hit. |
| `static/index.html`, `static/style.css` | Screens: start → in session → ended. Large RTL captions (tutor vs. Dad, each styled differently), a listening/speaking indicator, a big **"סיום"** ("end") button, a big **"אני חושב…"** button, and an **always-visible emergency button** that opens a full-screen BE-FAST message with "התקשרו למד״א 101" ("Call Magen David Adom 101"). |
| `static/app.js` | Session flow: get the token, open the WebSocket, send setup, stream the mic, play audio, show captions, handle interruptions, `goAway`/resume and the end of the session. |
| `static/audio/capture-worklet.js` | Mic → downsample to 16 kHz → Int16 chunks. |
| `static/audio/playback-worklet.js` | A 24 kHz PCM queue that can be flushed on interruption. |
| `tests/test_prompts.py` | YAML loads, placeholders render empty, key rules are present. |
| `tests/test_live_token.py` | A fake genai client: the token config locks the prompt, AUDIO, transcriptions, VAD and resumption, and has **no tools**; the key never appears in the response. |
| `tests/test_session_api.py` | `/api/session/start`: success, 503 without a key, 429 over the limit. |
| `requirements.txt` | Adds `google-genai`, `pyyaml`. |

## Tasks
1. [x] Draft `prompts/tutor.yaml` v0. **Tomer reviews the Hebrew wording.** Optionally try it in AI Studio's Live playground.
2. [x] Backend: prompts, token, rate limit, endpoint and tests.
3. [x] Frontend: worklets, WebSocket session, UI, emergency screen.
4. [x] Local test in desktop Chrome (`uvicorn`), then on a phone or tablet against Cloud Run, because the mic needs HTTPS.
5. [x] Tune the VAD silence time, the voice and the "I'm thinking" behaviour with Tomer.
6. [x] Deploy with `./deploy/deploy.sh`. Check the health endpoint and try it on the tablet.
7. [x] Commit and push.

## Manual steps for Tomer
- Review the Hebrew in the prompt and the UI.
- Test on the real device Dad will use (tablet or phone). Allow microphone access.
- Check the free-tier Live limits for the key in AI Studio (Rate limits page). They aren't published in the docs.

## Done when
- [x] `pytest` passes (29 tests).
- [x] A Hebrew conversation works locally and on Cloud Run, with about 1 s or less of latency before the tutor responds.
- [x] The tutor waits through a ~4 s pause, and talking over the tutor stops its audio immediately.
- [x] Captions show both sides in Hebrew.
- [x] The API key never reaches the browser (DevTools network tab: only the ephemeral token appears).
- [x] Minting a token is rate-limited.
- [x] The emergency button works on every screen.

## Commit
`Sub-plan 02: Gemini Live Hebrew voice tutor v0 with ephemeral tokens`

## Notes from doing it
- **Prompt** is in English (Tomer's choice), and the tutor always *speaks* Hebrew. The opening asks him what he'd like to talk about today, and the session is built around that topic (v0.3).
- **Patient profile:** his speech-language assessment shows a **mild** impairment. Language is largely preserved (WAB, naming 19/20, no dysarthria or apraxia). What remains is slower responses in long, complex speech and difficulty retrieving **proper names** (places, people). The therapist recommends working on naming and retrieval, message organization and high-level language. The generic prompt therefore adapts its level to a `{patient_profile}` section. The profile itself is **private**:
  - locally it's in `prompts/patient_profile.local.md`, which is gitignored and excluded from Docker and `.gcloudignore`
  - on GCP it's in a **private Cloud Storage bucket**, `gs://heb-practice-private/patient_profile.md`. Uniform access, public access prevented, and only the runtime service account has `objectViewer`. The app reads it directly (`PATIENT_PROFILE_URI`, `app/patient_profile.py`, cached 5 min). This was Tomer's choice over a secret: the profile stays only in the cloud, and no secret is used up. `setup_gcp.sh` uploads it; after that the local copy can be deleted.
- **Verified against the real API:** the ephemeral token works with `gemini-3.8-live` over the constrained WebSocket, and the tutor greets him in Hebrew using the masculine form.
- **Session resumption:** a handle the browser sends in `setup` is **ignored**, because the token's locked config wins. The handle has to be baked into the new token instead (`POST /api/session/start {"resume_handle": ...}`). Verified: the resumed session remembered a word from the earlier one.
- **Bug fixed:** the Dockerfile didn't copy `prompts/`, and the `.dockerignore` pattern only matched files in the project root.
- **Mic bug:** Chrome doesn't run an AudioWorklet node that isn't connected to an output, so no mic audio was ever sent. Fixed by routing it through a muted gain to the destination. Also added an on-screen mic-level meter. Start-of-speech sensitivity is HIGH (it catches quiet starts) and end-of-speech is LOW.
- **Tuning with Tomer:** the silence window is **3 s** (was 4.5 s). The voice is pinned to **"Kore"** (female), and the prompt (v0.4) makes the tutor refer to herself in the feminine; verified live ("אני שמחה"). The UI labels are feminine too ("המאמנת", "מקשיבה לך…").
- **Live captions of his speech:** Gemini sends the input transcript only **after** he finishes a turn (measured about 12 s after the start of a 4 s sentence). So Chrome's Web Speech API (`he-IL`, interim results) shows his words live, and Gemini's transcript replaces them when it arrives. Results that arrive while the tutor is speaking are ignored, to avoid captioning echo. Browsers without the Web Speech API fall back to Gemini-only captions.
- **Tutor image:** an illustrated SVG portrait (`static/tutor.svg`, no external assets). It gets a soft glowing ring while she speaks; it's not a moving avatar.
- **The tutor ends the call** (Tomer: this avoids confusion for Dad). This is the one exception to "no tools in the live model": a single `end_session` function, declared NON_BLOCKING, which the prompt (v0.5) tells her to call after her goodbye or when he asks to stop. The browser acknowledges it with SILENT scheduling and hangs up once her goodbye has finished playing (about 1.5 s of quiet, at most 20 s). Verified live: no call during normal conversation, and a warm goodbye plus `end_session` when he said he was tired.
- **Caption ordering bugs fixed** (Tomer saw lines out of order). (1) The tutor's text arrives before her audio, so the old "tutor is speaking = audio playing" check let late recognizer words open a stray line under her answer, and Gemini's transcript then landed there too. (2) `interrupted` didn't close his line, so later words joined an older line. The new logic is turn-based: his line stays open until her turn completes or is interrupted, so Gemini's late transcript joins the right line. The live recognizer is ignored while her turn is active, while her audio plays, and for 0.8 s afterwards (echo).
- **`end_session` wasn't called on a natural ending:** the prompt said "after your goodbye **and his reply**", so when he didn't answer, she waited forever. Prompt v0.6: call it right after the goodbye. The closing is now two turns (success question → wait → goodbye + hang-up), because she had been asking a question and saying goodbye in one breath. Verified live.
- **Debug mode:** open the app with `?debug=1` to get an on-screen event log (turns, audio start/stop, what Gemini heard, tool calls, socket closes). It's also available as `window.tutorLog` in the console. The conversation runs browser → Gemini, so there are no server logs for it.
- **Goodbye loop** (Tomer: "bye" → "להתראות" → "bye" → …). Verified against the real API that the model *does* call `end_session` on a spoken goodbye, so the loop was on the browser side. Fixes: (1) once `end_session` arrives, the mic stops being sent to Gemini and the live recognizer stops, so his "bye" can't start another round. The call closes after 1 s of silence, 12 s at most. (2) `Cache-Control: no-cache` on every response, so browsers revalidate and don't keep running a stale `app.js`.
- **Open question:** in one test, her *output transcription* contained Arabic words in place of Hebrew ones ("اليوم" for "היום"). This looks like a transcription artifact. Watch whether her audio ever actually switches language.
- **Hebrew:** native-audio models **ignore** `speech_config.language_code` (per the docs, they choose the language themselves), so it was removed. Hebrew is now enforced by a LANGUAGE rule that comes **first** in the system instruction (prompt v0.7). The `he-IL` hint stays on transcription, where it does apply. Verified live: English input ("Hi! I am fine…") got Hebrew-only replies.
- **The goodbye was cut off mid-sentence:** the hang-up relied on timing (1 s without a new chunk, 12 s cap). Long goodbyes and pauses in generation cut her off. It now hangs up only when her turn has **completed** (`turnComplete`, meaning all audio has been sent), the playback queue is drained, and a 0.7 s grace has passed. The safety cap is 30 s.
- **Deployed** as revision `hebrew-tutor-00004`: the profile is read from the private bucket, and the remote serves prompt 0.7.
- **Mishearing (Tomer: "sometimes it hears something different").** (1) **Audio bug fixed:** the worklet downsampled 48→16 kHz by picking samples without a low-pass filter, which aliases high frequencies into the speech band. Capture now runs in a 16 kHz AudioContext, so the browser resamples with proper filtering. The fallback path (Firefox) averages each output sample's window: a 15 kHz tone is attenuated about 12×, and speech is untouched. (2) The caption is Gemini's *separate* transcription; the voice model listens to the raw audio and can understand correctly even when the caption is wrong. (3) `Vocabulary: a, b, c` lines in the private profile become transcription `custom_vocabulary`, which biases recognition toward his names and places (`extract_vocabulary`).
- **Two-sided goodbye (Tomer: end only after he says goodbye back, like two people).** Prompt v0.8 and a new tool description: say goodbye, wait for his goodbye, then call `end_session`. The model still sometimes hung up in the same turn (1 of 3 runs), so **the browser enforces it**: `end_session` is accepted only if his last words match a goodbye pattern (להתראות / ביי / bye / ciao / נתראה / להפסיק…) or after a silence nudge. Otherwise it's refused with "wait for his goodbye, then call again". Verified live: refused → conversation continues → accepted after his "טוב, להתראות". A **30 s silence nudge** (sent once per silence) lets her end the call if he goes quiet after her goodbye, or check on him otherwise.
- **The call didn't end** (debug log): `end_session` was accepted, then Gemini closed the socket with `1011 service unavailable`, and the client **auto-reconnected** mid-hang-up. The goodbye turn never completed, so the hang-up waited for a `turnComplete` that never came. Fixes: a socket close while hanging up ends the session (no reconnect); `setupComplete` resets `modelActive`; an accepted `end_session` gets **no** toolResponse, since we're closing anyway and the 1011 came about 1 s after that reply. Verified live that `turnComplete` still arrives without the reply. The safety cap is now 20 s.
- **UI:** the session screen is exactly one window tall (header top, buttons pinned bottom, captions scroll in between, room reserved for the emergency button). Assets are served as `style.css?v=<content hash>` (the same for `app.js` and the worklets, via `import.meta.url`), so browsers can't keep stale copies across deploys. The buttons being cut off was a stale `style.css` cached before we sent Cache-Control headers.
- **Mute button (added 2026-10-02, Tomer's request): mutes the MICROPHONE only, like muting yourself on a call.** It isn't a pause: the session goes on, she keeps talking, and she still answers what he said last. While muted, the client **keeps streaming, but sends pure silence** instead of the mic. Background noise (TV, people talking) therefore can't interrupt her, and Gemini's voice detection still sees the silence after his last words, so it answers normally. (A first version stopped the stream and sent `audioStreamEnd`, which behaved like a pause; Tomer rejected it.) The live recognizer ignores the room while muted, the mic bar greys out, and the status shows "המיקרופון מושתק". The silence nudge runs as usual.
