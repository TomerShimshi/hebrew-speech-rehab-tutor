// Voice session: fetch a one-use ephemeral token from our backend, then talk to
// Gemini Live directly over a WebSocket (audio never passes through our server).
// The prompt/voice/VAD are locked into the token server-side; we only name the model.

const SESSION_WRAP_UP_MS = 9 * 60 * 1000; // ask the tutor to close at ~9 min (limit is 15)
const MIC_MIME = "audio/pcm;rate=16000";

// Short English stage directions the tutor receives as text (it always replies in Hebrew).
const NOTE_START = "[The patient just opened the app. Greet him and begin the session.]";
const NOTE_THINKING =
  "[He pressed the 'I'm thinking' button: he needs more time to find his words. " +
  "Say only a very short reassurance (like 'קח את הזמן'), then wait silently for him.]";
const NOTE_WRAP_UP =
  "[About 9 minutes have passed: time to wrap up. Let him finish what he is saying, then move " +
  "to the closing naturally.]";
const NOTE_SILENCE =
  "[He has been silent for 30 seconds. If you already said goodbye, call end_session now. " +
  "Otherwise gently check whether he is still there (one short question in Hebrew).]";
const SILENCE_NUDGE_MS = 30 * 1000;
const PAUSED_TEXT = "האימון מושהה כרגע, נחזור בקרוב 🙏";

const $ = (id) => document.getElementById(id);
// Carry app.js's ?v=<asset version> onto the worklets, so a deploy never runs stale audio code.
const ASSET_QUERY = new URL(import.meta.url).search;
const { initAuth, signIn, signOut, idToken } = await import(`./auth.js${ASSET_QUERY}`);
const screens = {
  signin: $("screen-signin"), start: $("screen-start"), session: $("screen-session"), ended: $("screen-ended"),
};
const FLUSH_MS = 10 * 1000; // transcript lines are saved every ~10 s (and at the end)

let s = null; // active session state

function show(name) {
  for (const [key, el] of Object.entries(screens)) el.hidden = key !== name;
}

function setIndicator(state) {
  const labels = { connecting: "מתחברת…", listening: "מקשיבה לך…", speaking: "מדברת…" };
  // While muted, the status says so (unless she's still finishing a sentence).
  const shown = s?.muted && state === "listening" ? "muted" : state;
  $("indicator").dataset.state = shown;
  $("indicator-text").textContent = shown === "muted" ? "המיקרופון מושתק" : labels[state];
  $("session-avatar").dataset.state = state;
  if (s) {
    const speaking = state === "speaking";
    if (speaking !== s.tutorAudio) {
      log("audio", speaking ? "tutor audio started" : "tutor audio stopped");
      // Whatever the recognizer heard while she was audible is her echo: skip past it,
      // and keep ignoring it for a moment after she stops (the recognizer lags).
      s.recBase = s.recCount;
      if (!speaking) s.echoUntil = performance.now() + 800;
    }
    s.tutorAudio = speaking;
    if (!speaking) s.gateOpen = false; // the noise filter re-arms for her next turn
  }
}

// ---- debug log (open the app with ?debug=1 to see it) -------------------------
const DEBUG = new URLSearchParams(location.search).has("debug");
if (DEBUG) {
  document.getElementById("debug-panel").hidden = false;
  document.getElementById("debug-copy").addEventListener("click", () =>
    navigator.clipboard.writeText(document.getElementById("debug-log").textContent));
}
const eventLog = [];
window.tutorLog = eventLog;
function log(kind, detail) {
  const t0 = s?.startedAt ?? performance.now();
  const entry = { t: ((performance.now() - t0) / 1000).toFixed(2), kind, detail };
  eventLog.push(entry);
  if (eventLog.length > 2000) eventLog.shift();
  if (DEBUG) {
    console.debug("[tutor]", entry.t, kind, detail);
    const panel = $("debug-log");
    panel.textContent += `${entry.t}s  ${kind}  ${detail}\n`;
    panel.scrollTop = panel.scrollHeight;
  }
}

// ---- captions ---------------------------------------------------------------
// Tutor lines come from Gemini's output transcription. His lines appear LIVE from the
// browser's speech recognizer (Gemini only sends its transcript after he finishes), and
// are then replaced by Gemini's version -- what the tutor actually heard.
//
// Ordering rules (turn-based, so late-arriving text never lands in the wrong place):
// - His line for the current turn (s.userLine) stays open until her reply COMPLETES or is
//   interrupted, so Gemini's transcript -- which can arrive after she starts -- joins it.
// - The live recognizer is ignored while her turn is active or her audio is playing
//   (that's her own voice, or his late words that Gemini's transcript will cover).
function newLine(speaker) {
  const line = document.createElement("div");
  line.className = `line ${speaker}`;
  line.innerHTML = `<span class="who">${speaker === "tutor" ? "המטפלת" : "אתה"}</span><span class="text"></span>`;
  const box = $("captions");
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
  const entry = {
    line, textEl: line.querySelector(".text"), live: "", gem: "", speaker,
    seq: s.nextSeq++, t: (performance.now() - s.startedAt) / 1000, interrupted: false,
  };
  return entry;
}

function renderUser(u) {
  markDirty(u);
  u.textEl.textContent = u.gem || u.live;
  u.line.classList.toggle("live", !u.gem);
  $("captions").scrollTop = $("captions").scrollHeight;
}

function ensureUserLine() {
  if (!s.userLine) {
    s.tutorLine = null;
    s.userLine = newLine("patient");
  }
  return s.userLine;
}

function onTutorOutput() {
  // First output (text or audio) of a new model turn.
  if (!s.modelActive) {
    s.modelActive = true;
    s.recBase = s.recCount;
    log("turn", "tutor turn started");
  }
}

function addTutorText(text) {
  onTutorOutput();
  if (!s.tutorLine) s.tutorLine = newLine("tutor");
  s.tutorLine.textEl.textContent += text;
  markDirty(s.tutorLine);
  $("captions").scrollTop = $("captions").scrollHeight;
}

function endTutorTurn(reason) {
  log("turn", `tutor turn ended (${reason})`);
  if (reason === "interrupted" && s.tutorLine) {
    s.tutorLine.interrupted = true; // he talked over her: keep that in the transcript
    markDirty(s.tutorLine);
  }
  s.modelActive = false;
  s.tutorLine = null;
  s.userLine = null; // his next words start a new line
  s.recBase = s.recCount;
}

function setUserLive(text) {
  s.lastUserAt = performance.now();
  const u = ensureUserLine();
  u.live = text;
  s.lastUserText = u.gem || u.live;
  renderUser(u);
}

function addUserFinal(text) {
  s.lastUserAt = performance.now();
  log("in", `gemini heard: ${text}`);
  const u = ensureUserLine();
  u.gem += text;
  s.lastUserText = u.gem;
  renderUser(u);
}

function recognizerMuted() {
  return s.muted || s.modelActive || s.tutorAudio || performance.now() < s.echoUntil;
}

function startLiveRecognizer() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return null; // e.g. Firefox: captions fall back to Gemini's transcript only
  const rec = new SR();
  rec.lang = "he-IL";
  rec.continuous = true;
  rec.interimResults = true;
  rec.onresult = (e) => {
    if (!s) return;
    s.recCount = e.results.length;
    if (recognizerMuted()) {
      s.recBase = s.recCount; // discard: her echo, or his late words Gemini's transcript covers
      return;
    }
    let text = "";
    for (let i = s.recBase; i < e.results.length; i++) text += e.results[i][0].transcript;
    if (text.trim()) setUserLive(text.trim());
  };
  rec.onerror = (e) => {
    log("recognizer", `error: ${e.error}`);
    if (e.error === "not-allowed" || e.error === "service-not-allowed") rec.onend = null;
  };
  rec.onend = () => {
    // Chrome stops continuous recognition periodically; restart while the session lasts.
    if (!s || s.ending) return;
    s.recBase = s.recCount = 0;
    try { rec.start(); } catch { /* already started */ }
  };
  try { rec.start(); } catch { return null; }
  return rec;
}

// ---- audio ------------------------------------------------------------------
function b64FromBuffer(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

function bufferFromB64(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

async function startAudio() {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  // Run the capture context at 16 kHz so the browser resamples the mic with proper
  // filtering (much cleaner for recognition). Browsers that can't mix rates (Firefox) fall
  // back to the device rate, and the worklet downsamples with its own low-pass.
  let capCtx = new AudioContext({ sampleRate: 16000 });
  let source;
  try {
    source = capCtx.createMediaStreamSource(stream);
  } catch {
    capCtx.close();
    capCtx = new AudioContext();
    source = capCtx.createMediaStreamSource(stream);
  }
  log("audio", `mic capture at ${capCtx.sampleRate} Hz`);
  await capCtx.audioWorklet.addModule(`audio/capture-worklet.js${ASSET_QUERY}`);
  const capNode = new AudioWorkletNode(capCtx, "capture-processor");
  source.connect(capNode);
  // Chrome only runs nodes that lead to an output: route through a muted gain.
  const mute = capCtx.createGain();
  mute.gain.value = 0;
  capNode.connect(mute).connect(capCtx.destination);
  capNode.port.onmessage = (e) => {
    if (s?.hangingUp) return; // she's hanging up: don't send his audio anymore
    // Tap-to-talk (09): his mic is sent only between "לדבר" and "סיימתי".
    if (s?.tapToTalk && !s.speaking) return;
    // Muted = the MIC is muted, nothing else: we keep streaming, but pure silence. Background
    // noise can't interrupt her, and Gemini still sees the silence after his last words, so it
    // answers him normally (stopping the stream instead could leave it waiting).
    const chunk = s?.muted ? new ArrayBuffer(e.data.byteLength) : e.data;
    if (!s?.muted) showMicLevel(e.data);
    if (!s?.muted && noiseGate(e.data)) return; // held or replaced by silence (09)
    sendJson({ realtimeInput: { audio: { data: b64FromBuffer(chunk), mimeType: MIC_MIME } } });
  };

  const playCtx = new AudioContext({ sampleRate: 24000 });
  await playCtx.audioWorklet.addModule(`audio/playback-worklet.js${ASSET_QUERY}`);
  const playNode = new AudioWorkletNode(playCtx, "playback-processor");
  playNode.connect(playCtx.destination);
  let quietTimer = null;
  playNode.port.onmessage = (e) => {
    // Debounce "stopped" so tiny gaps between chunks don't flicker the indicator.
    clearTimeout(quietTimer);
    if (e.data.playing) setIndicator("speaking");
    else quietTimer = setTimeout(() => setIndicator("listening"), 400);
  };
  // Contexts created after an await can start suspended; resume both explicitly.
  await Promise.all([capCtx.resume(), playCtx.resume()]);
  return { stream, capCtx, playCtx, playNode };
}

// Mic meter: visible proof that the app hears him (and a quick diagnostic for us).
let micLevel = 0;
function micRms(buf) {
  const pcm = new Int16Array(buf);
  let sum = 0;
  for (let i = 0; i < pcm.length; i++) sum += pcm[i] * pcm[i];
  return Math.sqrt(sum / pcm.length) / 0x8000;
}

function showMicLevel(buf) {
  const rms = micRms(buf);
  micLevel = Math.max(rms, micLevel * 0.85); // fast attack, slow decay
  $("mic-level").style.width = `${Math.min(100, micLevel * 400)}%`;
}

function stopAudio(audio) {
  if (!audio) return;
  audio.stream.getTracks().forEach((t) => t.stop());
  audio.capCtx.close();
  audio.playCtx.close();
}

// ---- Live WebSocket ---------------------------------------------------------
function sendJson(msg) {
  // Only after setupComplete: nothing may precede the setup message on a (re)connected socket.
  if (s && s.ready && s.ws.readyState === WebSocket.OPEN) s.ws.send(JSON.stringify(msg));
}

function sendNote(text) {
  sendJson({ realtimeInput: { text } });
}

// Every API call carries the Google sign-in token; the server checks it + the allowlist.
async function api(path, body, { keepalive = false } = {}) {
  return fetch(path, {
    method: body === undefined ? "GET" : "POST",
    keepalive, // lets the last transcript flush finish even while the tab is closing
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${await idToken()}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

async function fetchToken(resumeHandle) {
  const res = await api("api/session/start", {
    // The handle is baked into the new token server-side (the token's locked config wins);
    // on a reconnect the same session (and transcript) continues.
    resume_handle: resumeHandle || null,
    session_id: s.sessionId,
  });
  if (res.status === 401 || res.status === 403) throw new Error("צריך להתחבר מחדש כדי להמשיך.");
  const detail = res.ok ? "" : (await res.clone().json().catch(() => ({}))).detail;
  if (res.status === 429 && detail === "daily_limit") throw new Error("הגענו למכסת האימון של היום, נמשיך מחר 🙂");
  if (res.status === 409 && detail === "session_too_long") throw new Error("השיחה הזאת ארוכה מאוד, אז סיימנו להיום. נתראה בפעם הבאה 🙂");
  if (res.status === 429) throw new Error("נראה שהיו הרבה אימונים בשעה האחרונה. נסה שוב מאוחר יותר.");
  if (res.status === 503 && (await res.clone().json().catch(() => ({}))).detail === "paused") throw new Error(PAUSED_TEXT);
  if (!res.ok) throw new Error("לא הצלחנו להתחיל את האימון. נסה שוב בעוד רגע.");
  const t = await res.json();
  s.sessionId = t.session_id;
  if (t.start_note) s.startNote = t.start_note; // the greeting cue, with when they last talked
  if (t.game_homework) s.gameHomework = t.game_homework; // buttons for the end screen (06)
  setTapToTalk(!!t.voice?.tap_to_talk); // per-account setting (09)
  s.noiseLevel = t.voice?.noise_level || 0; // the noise filter level (09), adjusted after each session
  if (t.voice?.record_audio && !s.recorder) startRecording(); // once per session, across reconnects
  return t;
}

// ---- transcript saving --------------------------------------------------------
// Plain code, no LLM: every caption line has a seq; lines that changed are re-sent and the
// server upserts them by seq, so retries never duplicate.
function markDirty(line) {
  if (s && line) s.dirty.add(line);
}

function turnPayload(line) {
  return {
    seq: line.seq,
    speaker: line.speaker,
    text: line.speaker === "tutor" ? line.textEl.textContent : line.gem,
    live_text: line.speaker === "patient" ? line.live : "",
    t_start_s: Math.max(0, line.t),
    interrupted: !!line.interrupted,
  };
}

async function flushTurns(sess, { keepalive = false } = {}) {
  if (!sess?.sessionId || sess.dirty.size === 0 || sess.flushing) return;
  const lines = [...sess.dirty].slice(0, 50);
  lines.forEach((l) => sess.dirty.delete(l));
  sess.flushing = true;
  try {
    const res = await api(`api/session/${sess.sessionId}/turns`, { turns: lines.map(turnPayload) }, { keepalive });
    if (!res.ok && res.status !== 409) throw new Error(`HTTP ${res.status}`);
    log("save", `saved ${lines.length} line(s)`);
  } catch (err) {
    lines.forEach((l) => sess.dirty.add(l)); // retry on the next flush
    log("save", `flush failed: ${err.message}`);
  } finally {
    sess.flushing = false;
  }
  if (sess.dirty.size && !keepalive) await flushTurns(sess); // more than 50 were pending
}

async function finishRemote(sess, reason) {
  if (!sess.sessionId) return;
  await flushTurns(sess, { keepalive: true });
  try {
    log("save", `session ended (${reason}); updating memory…`);
    const res = await api(`api/session/${sess.sessionId}/end`, { reason }, { keepalive: true });
    const body = await res.json().catch(() => ({}));
    log("save", `memory update: ${body.memory_status ?? res.status}`);
  } catch (err) {
    log("save", `end failed: ${err.message}`); // next start marks it "abandoned"
  }
}

async function openSocket(isResume) {
  const t = await fetchToken(isResume ? s.resumeHandle : null);
  const ws = new WebSocket(`${t.ws_url}?access_token=${encodeURIComponent(t.token)}`);
  s.ws = ws;
  s.ready = false;
  ws.onopen = () => {
    ws.send(JSON.stringify({ setup: { model: `models/${t.model}` } }));
  };
  ws.onmessage = async (e) => {
    const raw = typeof e.data === "string" ? e.data : await e.data.text();
    handleServerMessage(JSON.parse(raw), isResume);
  };
  ws.onclose = (e) => {
    log("ws", `closed code=${e.code} reason=${e.reason || "-"}`);
    if (!s || s.ending || ws !== s.ws) return;
    // Already hanging up: the goodbyes are done, so just end -- never reconnect.
    if (s.hangingUp) return endSession(undefined, "tutor_goodbye");
    // Unexpected close (e.g. the ~10 min connection limit): resume with a fresh token.
    console.warn("Live socket closed", e.code, e.reason);
    reconnect();
  };
}

async function reconnect() {
  if (s.reconnects >= 3) return endSession("החיבור נותק. אפשר להתחיל אימון חדש.");
  s.reconnects += 1;
  setIndicator("connecting");
  try {
    await openSocket(true);
  } catch (err) {
    endSession(err.message);
  }
}

function handleServerMessage(msg, isResume) {
  if (msg.setupComplete) {
    log("ws", "setupComplete");
    s.reconnects = 0;
    s.ready = true;
    s.modelActive = false; // a fresh connection has no turn in progress
    setIndicator("listening");
    if (!isResume) sendNote(s.startNote || NOTE_START);
    return;
  }
  if (msg.sessionResumptionUpdate?.resumable && msg.sessionResumptionUpdate.newHandle) {
    s.resumeHandle = msg.sessionResumptionUpdate.newHandle;
  }
  if (msg.goAway) {
    log("ws", "goAway");
    // Server will close soon; switch to a fresh connection proactively.
    const old = s.ws;
    reconnect().then(() => old.close());
    return;
  }
  if (msg.toolCall) return handleToolCall(msg.toolCall);
  const sc = msg.serverContent;
  if (!sc) return;
  if (sc.interrupted) {
    s.audio.playNode.port.postMessage("flush");
    endTutorTurn("interrupted");
  }
  for (const part of sc.modelTurn?.parts || []) {
    if (part.inlineData?.data) {
      onTutorOutput();
      s.lastAudioAt = performance.now();
      const buf = bufferFromB64(part.inlineData.data);
      s.audio.playNode.port.postMessage(buf, [buf]);
    }
  }
  if (sc.inputTranscription?.text) addUserFinal(sc.inputTranscription.text);
  if (sc.outputTranscription?.text) addTutorText(sc.outputTranscription.text);
  if (sc.turnComplete) endTutorTurn("complete");
}

// Words that mean he is saying goodbye / wants to stop (Hebrew, plus common loanwords).
const GOODBYE_RE = /להתראות|ביי|bye|ciao|צ'?או|נתראה|יום טוב|ערב טוב|לילה טוב|שלום שלום|להפסיק|לסיים|מספיק להיום|די להיום/i;

// The tutor's only tool: she hangs up -- but, like two people, only after he said goodbye
// too. The model sometimes hangs up in the same breath as her own goodbye, so the browser
// enforces it: a premature call is refused, and she's told to wait and call again. After a
// silence nudge (he went quiet after her goodbye) the call is accepted.
function handleToolCall(toolCall) {
  const responses = [];
  for (const fc of toolCall.functionCalls || []) {
    let response = { ok: true };
    if (fc.name === "end_session") {
      const heSaidBye = GOODBYE_RE.test(s.lastUserText || "");
      if (heSaidBye || s.nudged) {
        log("tool", `end_session accepted (${heSaidBye ? "he said goodbye" : "after silence"})`);
        hangUpAfterGoodbye();
        continue; // no reply needed: we're closing (and a reply mid-goodbye can upset the session)
      } else {
        log("tool", `end_session refused: his last words were not a goodbye ("${s.lastUserText}")`);
        response = {
          ok: false,
          result: "Not ended: he has not said goodbye yet. Wait for his goodbye, then call end_session again.",
        };
      }
    }
    responses.push({ id: fc.id, name: fc.name, response, scheduling: "SILENT" });
  }
  if (responses.length) sendJson({ toolResponse: { functionResponses: responses } });
}

function hangUpAfterGoodbye() {
  if (s.hangingUp) return;
  s.hangingUp = true;
  // Stop listening right away: otherwise his "bye" starts another goodbye round (a loop).
  s.rec?.abort();
  log("tool", "hanging up: mic muted, waiting for her goodbye to finish");
  const startedAt = performance.now();
  let doneSince = 0;
  // Hang up only once her goodbye is COMPLETE: Gemini has finished the turn (turnComplete:
  // all its audio has arrived) AND the playback queue has drained. Timing-only rules cut
  // her off mid-sentence -- generation can pause, and goodbyes can be long.
  const timer = setInterval(() => {
    const now = performance.now();
    const done = !s || (!s.modelActive && !s.tutorAudio);
    doneSince = done ? doneSince || now : 0;
    const finished = done && now - doneSince > 700; // small grace after the last word
    if (finished || now - startedAt > 20000) {
      if (!finished) log("tool", "hang-up safety cap reached");
      clearInterval(timer);
      endSession(undefined, "tutor_goodbye");
    }
  }, 200);
}

// ---- session lifecycle ------------------------------------------------------
async function startSession() {
  const status = $("start-status");
  $("talk").disabled = true;
  status.textContent = "מתכוננים…";
  s = {
    ws: null, ready: false, audio: null, resumeHandle: null, reconnects: 0, ending: false,
    startedAt: performance.now(), tutorLine: null, userLine: null, modelActive: false,
    rec: null, recBase: 0, recCount: 0, tutorAudio: false, echoUntil: 0,
    lastAudioAt: 0, hangingUp: false, lastUserAt: performance.now(), nudged: false,
    lastUserText: "", sessionId: null, nextSeq: 0, dirty: new Set(), flushing: false, muted: false,
    tapToTalk: false, speaking: false, noiseLevel: 0, gateOpen: false, loudSince: 0, gateBuffer: [],
    recorder: null, recChunks: [], recMicGain: null,
  };
  try {
    s.audio = await startAudio(); // inside the click handler: required to unlock audio on tablets
  } catch (err) {
    console.error(err);
    s = null;
    $("talk").disabled = false;
    status.textContent = "צריך לאשר גישה למיקרופון כדי שנוכל לדבר.";
    return;
  }
  $("captions").replaceChildren();
  $("mute").classList.remove("active");
  $("mute").setAttribute("aria-pressed", "false");
  $("mute").textContent = "🔇 השתקה";
  document.querySelector(".mic").classList.remove("muted");
  s.rec = startLiveRecognizer();
  show("session");
  setIndicator("connecting");
  try {
    await openSocket(false);
  } catch (err) {
    return endSession(err.message);
  }
  // The tutor never starts closing on her own (prompt); this note tells her when. It waits for a
  // quiet moment -- not while she talks or right after he spoke -- so it never cuts a thread.
  s.wrapTimer = setTimeout(() => { if (s) s.wrapDue = true; }, SESSION_WRAP_UP_MS);
  const sess = s;
  s.flushTimer = setInterval(() => flushTurns(sess), FLUSH_MS);
  // If he goes quiet after she finished talking (e.g. after her goodbye, or he walked away),
  // tell her once; she decides whether to hang up or check on him.
  s.silenceTimer = setInterval(() => {
    if (!s || s.hangingUp || s.modelActive || s.tutorAudio) return;
    if (s.speaking) { s.lastUserAt = performance.now(); return; } // tap-to-talk: he holds the turn
    if (s.wrapDue && performance.now() - Math.max(s.lastUserAt, s.lastAudioAt) > 2000) {
      s.wrapDue = false;
      log("ui", "wrap-up note sent");
      sendNote(NOTE_WRAP_UP);
      return;
    }
    const quietFor = performance.now() - Math.max(s.lastUserAt, s.lastAudioAt);
    if (quietFor < SILENCE_NUDGE_MS) {
      s.nudged = false;
    } else if (!s.nudged) {
      s.nudged = true;
      log("ui", "silence nudge sent");
      sendNote(NOTE_SILENCE);
    }
  }, 1000);
  try {
    s.wakeLock = await navigator.wakeLock?.request("screen"); // keep the tablet screen on
  } catch { /* not supported: fine */ }
}

// The game homework the tutor suggested, as big buttons that open the Simon game on his
// profile (links come from the server, built from the catalog -- never from the model).
function showGameHomework(items) {
  const box = $("game-homework-buttons");
  box.replaceChildren(...items.map((g) => {
    const a = document.createElement("a");
    a.href = g.url;
    a.target = "_blank";
    a.rel = "noopener";
    a.className = "big primary";
    a.textContent = `🎮 ${g.name_he}`;
    return a;
  }));
  $("game-homework").hidden = items.length === 0;
}

function endSession(errorMessage, reason = errorMessage ? "error" : "end_button") {
  if (!s) return;
  const sess = s;
  log("session", errorMessage ? `ended with error: ${errorMessage}` : `ended (${reason})`);
  s.ending = true;
  clearTimeout(s.wrapTimer);
  clearInterval(s.silenceTimer);
  clearInterval(s.flushTimer);
  finishRemote(s, reason); // final transcript flush + mark the session ended (async)
  s.rec?.abort();
  s.ws?.close();
  // The recording must be finished before the audio shuts down; then it's uploaded (09).
  const audio = s.audio;
  stopRecording(sess).then((blob) => {
    stopAudio(audio);
    uploadRecording(sess.sessionId, blob);
  });
  s.wakeLock?.release?.();
  s = null;
  $("talk").disabled = false;
  if (errorMessage) {
    $("start-status").textContent = errorMessage;
    $("start-status").classList.toggle("paused-note", errorMessage === PAUSED_TEXT);
    show("start");
  } else {
    $("start-status").textContent = "";
    $("start-status").classList.remove("paused-note");
    showGameHomework(sess.gameHomework || []);
    show("ended");
  }
}

$("talk").addEventListener("click", startSession);
$("end").addEventListener("click", () => { log("ui", "end button"); endSession(undefined, "end_button"); });
$("again").addEventListener("click", () => show("start"));
// Mute = mute the MICROPHONE only (like muting yourself on a call): the session goes on as
// usual -- she keeps talking and still answers what he said last -- but background noise
// (TV, people talking) can't interrupt her. See the capture handler: silence is streamed.
function setMuted(muted) {
  if (!s) return;
  s.muted = muted;
  if (s.recMicGain) s.recMicGain.gain.value = muted ? 0 : 1; // muted = not recorded either
  if (muted) {
    $("mic-level").style.width = "0%";
  } else {
    s.recBase = s.recCount; // drop anything the live recognizer picked up while muted
  }
  log("ui", muted ? "muted" : "unmuted");
  const btn = $("mute");
  btn.classList.toggle("active", muted);
  btn.setAttribute("aria-pressed", String(muted));
  btn.textContent = muted ? "🎤 החזרת הקול" : "🔇 השתקה";
  document.querySelector(".mic").classList.toggle("muted", muted);
  setIndicator(s.tutorAudio ? "speaking" : "listening");
}

$("mute").addEventListener("click", () => setMuted(!s?.muted));

// ---- noise filter (09): only while SHE is speaking, his mic passes only if the sound is loud
// and long enough to be speech (~0.3 s); a short bang or a far-away TV becomes silence, so it
// can't interrupt her. The held audio is sent as soon as it qualifies, so no word is lost.
// When she's quiet, everything passes (his own turns are never filtered).
const NOISE_GATE_RMS = { 1: 0.015, 2: 0.03, 3: 0.05 };
const NOISE_GATE_HOLD_MS = 300;
function sendSilence(buf) {
  sendJson({ realtimeInput: { audio: { data: b64FromBuffer(new ArrayBuffer(buf.byteLength)), mimeType: MIC_MIME } } });
}
function noiseGate(buf) {
  if (!s?.noiseLevel || s.tapToTalk || !s.tutorAudio || s.gateOpen) return false; // pass through
  const now = performance.now();
  if (micRms(buf) >= NOISE_GATE_RMS[s.noiseLevel]) {
    if (!s.loudSince) s.loudSince = now;
    s.gateBuffer.push(buf);
    if (now - s.loudSince >= NOISE_GATE_HOLD_MS) { // sustained: that's him -- let it through
      s.gateOpen = true;
      log("audio", `noise filter opened (level ${s.noiseLevel})`);
      for (const held of s.gateBuffer) sendJson({ realtimeInput: { audio: { data: b64FromBuffer(held), mimeType: MIC_MIME } } });
      s.gateBuffer = [];
      s.loudSince = 0;
    }
    return true; // held for now
  }
  for (const held of s.gateBuffer) sendSilence(held); // it was a short noise: send silence instead
  s.gateBuffer = [];
  s.loudSince = 0;
  sendSilence(buf);
  return true;
}

// ---- session recording (09): both voices, for the caregiver page only --------------------------
// Mixed in the playback context: his mic (silent while muted) + her speech, recorded by the
// browser (Opus in WebM; MP4 on Safari) and uploaded once when the session ends.
function startRecording() {
  if (!window.MediaRecorder || !s?.audio) return;
  try {
    const { stream, playCtx, playNode } = s.audio;
    const dest = playCtx.createMediaStreamDestination();
    s.recMicGain = playCtx.createGain();
    s.recMicGain.gain.value = s.muted ? 0 : 1;
    playCtx.createMediaStreamSource(stream).connect(s.recMicGain).connect(dest);
    playNode.connect(dest);
    const type = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported(t));
    s.recorder = new MediaRecorder(dest.stream, { ...(type ? { mimeType: type } : {}), audioBitsPerSecond: 24000 });
    s.recChunks = [];
    s.recorder.ondataavailable = (e) => { if (e.data.size) s?.recChunks.push(e.data); };
    s.recorder.start(10000); // a chunk every 10 s
    log("audio", `recording (${s.recorder.mimeType})`);
  } catch (err) {
    log("audio", `recording unavailable: ${err.message}`); // the session goes on without it
    s.recorder = null;
  }
}

// Stops the recorder; resolves with the finished file (or null).
function stopRecording(sess) {
  const rec = sess.recorder;
  if (!rec || rec.state === "inactive") return Promise.resolve(null);
  return new Promise((resolve) => {
    const chunks = sess.recChunks;
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = () => resolve(chunks.length ? new Blob(chunks, { type: rec.mimeType.split(";")[0] }) : null);
    setTimeout(() => resolve(chunks.length ? new Blob(chunks, { type: rec.mimeType.split(";")[0] }) : null), 3000);
    rec.stop();
  });
}

async function uploadRecording(sessionId, blob) {
  if (!sessionId || !blob) return;
  try {
    const res = await fetch(`api/session/${encodeURIComponent(sessionId)}/audio`, {
      method: "POST", body: blob,
      headers: { "Content-Type": blob.type || "audio/webm", Authorization: `Bearer ${await idToken()}` },
    });
    log("audio", `recording uploaded: ${res.status} (${Math.round(blob.size / 1024)} KB)`);
  } catch (err) {
    log("audio", `recording upload failed: ${err.message}`);
  }
}

// ---- daily reminder notification (11) ------------------------------------------------------
// A permanent line on his start screen: "🔔 ... every day at 10:00 · change". Turning it on is
// one tap per device (the browser asks permission; the device subscribes) and also switches the
// reminder on for his account. He can pick the hour himself; the caregiver page can too.
const pushSupported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
const REMINDER_HOURS = [8, 10, 13, 17, 19];
let myReminder = null; // {enabled, hour, days} for this account, from /api/me
const hh = (h) => `${String(h).padStart(2, "0")}:00`;

function urlBase64ToUint8Array(b64) {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

async function sendSubscription(sub) {
  const res = await api("api/push/subscribe", { subscription: sub.toJSON() });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

async function saveMyReminder(enabled, hour) {
  const res = await fetch("api/reminder", {
    method: "PUT", body: JSON.stringify({ enabled, hour }),
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${await idToken()}` },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  myReminder = await res.json();
}

function renderReminder(subscribed) {
  $("reminder-box").hidden = false;
  $("reminder-times").hidden = true;
  const denied = Notification.permission === "denied";
  $("push-enable").hidden = subscribed || denied;
  $("reminder-state").hidden = !subscribed;
  if (denied && !subscribed) {
    $("push-status").textContent = "התזכורות חסומות בדפדפן. אפשר להפעיל אותן בהגדרות האתר.";
    return;
  }
  if (!subscribed) return;
  const on = !!myReminder?.enabled;
  const days = myReminder?.days?.length === 7 ? "כל יום" : "בימים שנבחרו";
  const change = el("button", { class: "link", type: "button", text: on ? "שינוי" : "להפעיל" });
  change.addEventListener("click", () => {
    $("reminder-times").hidden = !$("reminder-times").hidden;
  });
  $("reminder-state").replaceChildren(on ? `🔔 תזכורת יומית ${days} ב־${hh(myReminder.hour)} · ` : "🔕 התזכורת כבויה · ", change);
  $("reminder-off").hidden = !on;
  $("reminder-times").querySelector(".reminder-buttons").replaceChildren(...REMINDER_HOURS.map((h) => {
    const b = el("button", { type: "button", class: on && myReminder.hour === h ? "on" : "", text: hh(h) });
    b.addEventListener("click", async () => {
      try {
        await saveMyReminder(true, h);
        $("push-status").textContent = `✓ התזכורת תגיע כל יום ב־${hh(h)}`;
      } catch {
        $("push-status").textContent = "השמירה לא הצליחה. נסה שוב.";
      }
      renderReminder(true);
    });
    return b;
  }));
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "text") node.textContent = v; else if (k === "class") node.className = v; else node.setAttribute(k, v);
  }
  node.append(...children);
  return node;
}

async function setupPush(reminder) {
  myReminder = reminder || myReminder;
  if (!pushSupported) return;
  try {
    const reg = await navigator.serviceWorker.register("sw.js");
    const existing = await reg.pushManager.getSubscription();
    const subscribed = !!existing && Notification.permission === "granted";
    if (subscribed) await sendSubscription(existing); // keep the server's copy current
    renderReminder(subscribed);
  } catch (err) {
    log("push", `setup failed: ${err.message}`);
  }
}

$("push-enable").addEventListener("click", async () => {
  try {
    if ((await Notification.requestPermission()) !== "granted") {
      $("push-status").textContent = "בלי אישור לא נוכל לשלוח תזכורת. אפשר לנסות שוב בכל זמן.";
      return;
    }
    const key = (await (await api("api/push/public-key")).json()).key;
    if (!key) throw new Error("no key");
    const reg = await navigator.serviceWorker.ready;
    const sub = (await reg.pushManager.getSubscription())
      || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(key) });
    await sendSubscription(sub);
    await saveMyReminder(true, myReminder?.hour ?? 10); // on for his account too
    $("push-status").textContent = `✓ התזכורת היומית הופעלה. אפשר לבחור שעה אחרת ב"שינוי".`;
    renderReminder(true);
  } catch (err) {
    log("push", `enable failed: ${err.message}`);
    $("push-status").textContent = "ההפעלה לא הצליחה. נסה שוב בעוד רגע.";
  }
});

$("reminder-off").addEventListener("click", async () => {
  try {
    await saveMyReminder(false);
    $("push-status").textContent = "התזכורת כובתה. אפשר להפעיל אותה שוב בכל זמן.";
  } catch {
    $("push-status").textContent = "לא הצלחנו לכבות. נסה שוב.";
  }
  renderReminder(true);
});

// ---- tap-to-talk (09): he marks his own turn; automatic detection is off for this account --
function setTapToTalk(on) {
  s.tapToTalk = on;
  s.speaking = false; // a new connection starts between turns
  $("talk-toggle").hidden = !on;
  $("mute").hidden = on; // nothing to mute: the mic is only sent while he holds the turn
  showSpeaking();
}
function showSpeaking() {
  const btn = $("talk-toggle");
  btn.textContent = s?.speaking ? "✅ סיימתי" : "🎙️ לדבר";
  btn.classList.toggle("active", !!s?.speaking);
  btn.setAttribute("aria-pressed", String(!!s?.speaking));
}
$("talk-toggle").addEventListener("click", () => {
  if (!s || s.hangingUp) return;
  s.speaking = !s.speaking;
  // activityStart also interrupts her if she's talking -- like him starting to speak.
  sendJson({ realtimeInput: s.speaking ? { activityStart: {} } : { activityEnd: {} } });
  log("ui", s.speaking ? "tap: speaking" : "tap: done");
  if (s.speaking) s.lastUserAt = performance.now();
  showSpeaking();
});

$("thinking").addEventListener("click", () => {
  sendNote(NOTE_THINKING);
  const btn = $("thinking");
  btn.classList.add("active");
  setTimeout(() => btn.classList.remove("active"), 1500);
});
// Tab closing mid-session: save what we have. The session stays "active" and is marked
// "abandoned" on the next start (its transcript is kept).
window.addEventListener("pagehide", () => { if (s) flushTurns(s, { keepalive: true }); });

// ---- sign-in -----------------------------------------------------------------
function signinMessage(text, offerSwitch = false) {
  $("signin-status").textContent = text;
  $("signin-switch").hidden = !offerSwitch;
}

async function onUserChanged(user) {
  if (s) return; // never interrupt a running session
  if (!user) {
    show("signin");
    return;
  }
  const res = await api("api/me").catch(() => null);
  if (res?.ok) {
    const me = await res.json();
    $("admin-open").hidden = !me.is_caregiver; // Dad never sees it; the server enforces it too
    $("recording-note").hidden = !me.recording; // he's told when sessions are recorded (09)
    setupPush(me.reminder); // the daily reminder line (11)
    // Soft stop on spending (10): practice is paused until a caregiver resumes it.
    $("talk").disabled = !!me.paused;
    $("start-status").textContent = me.paused ? PAUSED_TEXT : "";
    $("start-status").classList.toggle("paused-note", !!me.paused);
    signinMessage("");
    show("start");
  } else if (res?.status === 403) {
    show("signin");
    signinMessage(`החשבון ${user.email} לא מורשה להשתמש באפליקציה.`, true);
  } else {
    show("signin");
    signinMessage("לא הצלחנו להתחבר לשרת. נסה שוב בעוד רגע.");
  }
}

$("signin").addEventListener("click", async () => {
  signinMessage("");
  try {
    await signIn();
  } catch (err) {
    log("auth", `sign-in failed: ${err.code || err.message}`);
    signinMessage("ההתחברות לא הצליחה. נסה שוב.");
  }
});
$("signin-switch").addEventListener("click", () => signOut());

// ---- caregiver page (08): its own page; the server only serves data to caregivers ----
$("admin-open").addEventListener("click", () => { window.location.href = "caregiver"; });
$("signout").addEventListener("click", () => signOut());

try {
  await initAuth(onUserChanged);
} catch (err) {
  log("auth", `init failed: ${err.message}`);
  signinMessage("ההתחברות עדיין לא מוגדרת בשרת.");
}

// The server sleeps when idle (Cloud Run scales to zero; waking takes ~10 s). Wake it as soon as
// the app is on screen -- also when he returns to a tab left open -- so it's ready by his tap.
const warmUp = () => { if (document.visibilityState === "visible" && !s) fetch("api/health").catch(() => {}); };
warmUp();
document.addEventListener("visibilitychange", warmUp);

$("emergency").addEventListener("click", () => { $("emergency-overlay").hidden = false; });
$("emergency-close").addEventListener("click", () => { $("emergency-overlay").hidden = true; });
