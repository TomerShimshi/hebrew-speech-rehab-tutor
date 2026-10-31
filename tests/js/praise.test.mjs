// tests/js/praise.test.mjs -- run: node --test tests/js/*.test.mjs
// His streak line on the start screen (21): a number only when it's a real streak, never a sad one.
import { test } from "node:test";
import assert from "node:assert/strict";
import { streakLine } from "../../static/praise.js";

test("a streak gets its number and a compliment", () => {
  const line = streakLine({ days: 5, today: true });
  assert.equal(line.title, "5 ימים ברצף");
  assert.ok(line.praise.length > 0);
});

test("the compliment grows with the streak", () => {
  assert.notEqual(streakLine({ days: 2 }).praise, streakLine({ days: 14 }).praise);
});

test("one day, and zero, are never a sad number", () => {
  const zero = streakLine({ days: 0, today: false });
  assert.equal(zero.title, "היום מתחילים רצף חדש");
  const one = streakLine({ days: 1, today: true });
  for (const line of [zero, one]) assert.ok(!/\b0\b/.test(line.title + line.praise));
  assert.equal(streakLine(undefined).title, "היום מתחילים רצף חדש");  // /api/me without it (an old server)
});
