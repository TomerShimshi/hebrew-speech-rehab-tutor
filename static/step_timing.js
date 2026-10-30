// When the page answers her next_step call (20.5 B). She often calls it while still saying her reaction;
// once the reply arrives Gemini starts the next step and drops whatever of the reaction hadn't played yet
// (30.10: cut mid-word twice). So the reply waits until her audio has stopped -- but never less than the
// transcript catch-up (the question guard reads her transcript) and never more than a cap.
// Dependency-free: the page imports it, and `node --test tests/js/*.test.mjs` tests it as is.

export const TRANSCRIPT_CATCHUP_MS = 1200; // her transcript lags behind her audio (12.10)
export const QUIET_GRACE_MS = 300; // her audio arrives in chunks: a short gap isn't the end
export const STEP_REPLY_CAP_MS = 10000; // a step never waits forever

export function readyToAnswerStep({ sinceCallMs, herAudioPlaying, quietMs }) {
  if (sinceCallMs >= STEP_REPLY_CAP_MS) return true;
  return sinceCallMs >= TRANSCRIPT_CATCHUP_MS && !herAudioPlaying && quietMs >= QUIET_GRACE_MS;
}
