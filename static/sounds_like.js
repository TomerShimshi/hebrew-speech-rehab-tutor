// Does his names-game answer sound like the name? (20) The page knows the names it expects, and the
// transcripts' Hebrew errors are predictable: a missing vowel letter, ט for ת, ק for כ, a cut first
// sound. So both are reduced to a consonant skeleton and compared with a small edit distance.
// Dependency-free: the page imports it, and `node --test tests/js/*.test.mjs` tests it as is.

const MARKS = /[֑-ׇ]/g; // vowel marks and cantillation (incl. the shin/sin dots)
const FINALS = { "ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ" };
// letters that sound alike count as one
const ALIKE = { "ט": "ת", "ק": "כ", "ח": "כ", "ש": "ס", "ע": "א", "ה": "א" };

function words(text) {
  return (text || "").replace(MARKS, "").replace(/[^א-תa-zA-Z0-9]+/g, " ").trim().split(" ").filter(Boolean);
}

function wordSkeleton(word) {
  let out = "";
  [...word].forEach((ch, i) => {
    ch = FINALS[ch] || ch;
    if (i > 0 && (ch === "ו" || ch === "י")) return; // a vowel letter -- except a word's first letter
    if (i === 0 && ch === "ו") ch = "ב"; // ב/ו at a word's start
    out += ALIKE[ch] || ch;
  });
  return out.toLowerCase();
}

// The consonant skeleton of a text: its words' skeletons, joined.
export function skeleton(text) {
  return words(text).map(wordSkeleton).join("");
}

function editDistance(a, b) {
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    prev = cur;
  }
  return prev[b.length];
}

// The distance allowed for a target skeleton of this length: a short name must match exactly.
const allowed = (n) => (n <= 3 ? 0 : n <= 6 ? 1 : 2);

// True when a run of 1-3 consecutive words in `heard` sounds like `target`.
export function soundsLike(heard, target) {
  const want = skeleton(target);
  if (!want) return false;
  const ws = words(heard).map(wordSkeleton);
  for (let i = 0; i < ws.length; i++) {
    let run = "";
    for (let j = i; j < Math.min(i + 3, ws.length); j++) {
      run += ws[j];
      if (Math.abs(run.length - want.length) > 1) continue;
      if (editDistance(run, want) <= allowed(want.length)) return true;
    }
  }
  return false;
}

// Her reply after an answer the page matched: did she treat it as wrong? Only when she gives no praise
// and either says the name herself (the game's rule for a wrong answer) or asks him to say it again.
// Moving on counts as accepting it: a correction then made her repeat the question (29.10, "מדויק!").
const PRAISE = /נכון|כל הכבוד|מצוין|בדיוק|יפה|יופי|מדויק|נהדר|מעולה|אלוף|צודק|מושלם|בול/;
const ASKS_AGAIN = /לא שמעתי|תגיד שוב|תחזור/;
export function herReplyRejected(herText, target) {
  if (!herText || PRAISE.test(herText)) return false;
  return ASKS_AGAIN.test(herText) || soundsLike(herText, target);
}
