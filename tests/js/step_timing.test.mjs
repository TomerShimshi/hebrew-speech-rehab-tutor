// tests/js/step_timing.test.mjs -- run: node --test tests/js/*.test.mjs
// When the page answers her next_step call (20.5 B): only after her reaction finished playing.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readyToAnswerStep } from "../../static/step_timing.js";

test("not before the transcript catch-up, even when she is quiet", () =>
  assert.ok(!readyToAnswerStep({ sinceCallMs: 500, herAudioPlaying: false, quietMs: 500 })));
test("not while her reaction is still playing", () =>
  assert.ok(!readyToAnswerStep({ sinceCallMs: 3000, herAudioPlaying: true, quietMs: 0 })));
test("not in a gap between two chunks of her audio", () =>
  assert.ok(!readyToAnswerStep({ sinceCallMs: 3000, herAudioPlaying: false, quietMs: 100 })));
test("after she has been quiet for the grace", () =>
  assert.ok(readyToAnswerStep({ sinceCallMs: 3000, herAudioPlaying: false, quietMs: 300 })));
test("the cap: never waits more than 10 s", () =>
  assert.ok(readyToAnswerStep({ sinceCallMs: 10000, herAudioPlaying: true, quietMs: 0 })));
