// tests/js/sounds_like.test.mjs -- run: node --test tests/js/
// The page's match of his names-game answer (20). Invented names and words only.
import { test } from "node:test";
import assert from "node:assert/strict";
import { soundsLike, skeleton, herReplyRejected } from "../../static/sounds_like.js";

test("the transcripts' usual Hebrew errors still match", () => {
  assert.ok(soundsLike("טבריה", "תבריה"));          // ט/ת
  assert.ok(soundsLike("זה כרמל", "קרמל"));         // כ/ק, inside a longer line
  assert.ok(soundsLike("הוֹלַנְד", "הולנד"));          // vowel marks
  assert.ok(soundsLike("ירושלים", "ירושלם"));       // a vowel letter missing
  assert.ok(soundsLike("תל אביב", "תל-אביב"));      // two words, punctuation
  assert.ok(soundsLike("רושלים", "ירושלים"));       // the start cut (distance 1, length 5)
});

test("no false matches", () => {
  assert.ok(!soundsLike("אני לא יודע", "דני"));     // a short name: exact skeleton only
  assert.ok(!soundsLike("שולחן", "שלום"));
  assert.ok(!soundsLike("", "חיפה"));
  assert.ok(!soundsLike("בייגלה", "בגדד"));
  assert.ok(!soundsLike("כן", "דן"));               // a short name one sound from a common word
  assert.ok(!soundsLike("חיפה", ""));
});

test("final forms are regular letters", () => {
  assert.equal(skeleton("ים"), skeleton("ימ"));
});

// Her reply after an answer the page matched (20): she's corrected only when she treated it as wrong.
test("her reply moving on is not a rejection, whatever her praise word", () => {
  assert.ok(!herReplyRejected("מדויק! ואיזו עיר נמצאת על הכנרת?", "תבריה")); // 29.10: "מדויק" led to a repeat
  assert.ok(!herReplyRejected("נהדר. ועכשיו השאלה הבאה:", "תבריה"));
  assert.ok(!herReplyRejected("נכון, טבריה! והבאה?", "תבריה"));          // praise and the name
  assert.ok(!herReplyRejected("", "תבריה"));
});

test("her reply saying the name herself, or asking again, is a rejection", () => {
  assert.ok(herReplyRejected("קרוב, זו טבריה. ועכשיו הבאה:", "תבריה")); // rule 3: she says the name
  assert.ok(herReplyRejected("סליחה, לא שמעתי טוב, תגיד שוב?", "תבריה")); // rule 2: she asks again
});
