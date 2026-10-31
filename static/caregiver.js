// Caregiver page (08): one view per allowlisted account. All data comes from /api/caregiver/*,
// which only answers caregivers. Everything from the server is shown as TEXT (textContent),
// never as HTML: transcripts and memories contain whatever was said.
const ASSET_QUERY = new URL(import.meta.url).search;
const { initAuth, signIn, signOut, idToken } = await import(`./auth.js${ASSET_QUERY}`);

const $ = (id) => document.getElementById(id);
const ACCOUNT_KEY = "caregiver.account";

const MOOD = { good: "מצב רוח טוב", ok: "מצב רוח בסדר", low: "מצב רוח ירוד", unknown: "" };
const RESULT = { uncued: "✓", cued: "~", failed: "✗", self_found: "★", not_found: "…" };
const RESULT_TEXT = { uncued: "לבד", cued: "עם רמז", failed: "לא הצליח", self_found: "מצא לבד בשיחה",
                      not_found: "לא מצא בשיחה" };
// where a word-bank name came from (12): only "practiced" counts as practiced in the names game
const SOURCE = { practiced: "תורגל", self_found: "מצא לבד", not_found: "לא מצא", probe: "משחק השמות (חדש)" };
const GAME_STATUS = { played: "שוחק", skipped: "דולג", not_reached: "לא הגיעו אליו" };
const FLAG_KIND = { sudden_decline: "ירידה פתאומית", distress: "מצוקה", safety: "בטיחות", technical: "תקלה טכנית",
                    tutor_issue: "טעות של המטפלת" };
const END_REASON = { end_button: "כפתור סיום", tutor_goodbye: "המטפלת סיימה", abandoned: "החלון נסגר",
                     error: "תקלה" };
const GOAL = { name_retrieval: "שליפת שמות", discourse: "סיפור והסבר", high_level_language: "שפה גבוהה",
               conversation: "שיחה חופשית" };
const SECTION = { personal_facts: "עובדות אישיות", interests: "תחומי עניין", what_works: "מה עובד",
                  what_to_avoid: "ממה להימנע", language_observations: "תצפיות על הדיבור",
                  homework_given: "משימה שניתנה" };
const STATUS = { new: "חדש", accepted: "התקבל", rejected: "נדחה", done: "בוצע" };

let account = "";
let accounts = [];
let lastOverview = null; // kept for the therapist export (09)
let lastSessions = [];

// ---- small DOM helpers (text only) ----------------------------------------------
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "text") node.textContent = value;
    else if (key === "class") node.className = value;
    else if (key === "onclick") node.addEventListener("click", value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}
const p = (text, cls) => el("p", { text, class: cls, dir: "auto" });

// "Working on it" status: the text plus three moving dots, until it is replaced.
function busy(target, text) {
  target.replaceChildren(el("span", { class: "busy" }, text, el("span", { class: "dots", "aria-hidden": "true" },
    el("i"), el("i"), el("i"))));
}

// A button that asks "sure?" inline before doing something that changes data.
function confirmButton(label, question, action, cls = "small") {
  const wrap = el("span", {});
  const button = el("button", { class: cls, type: "button", text: label });
  button.addEventListener("click", () => {
    const yes = el("button", { class: "yes", type: "button", text: "כן" });
    const no = el("button", { type: "button", text: "ביטול" });
    no.addEventListener("click", () => wrap.replaceChildren(button));
    yes.addEventListener("click", async () => {
      yes.disabled = no.disabled = true;
      await action(wrap); // the action can show its progress right here, where the click was
    });
    wrap.replaceChildren(el("span", { class: "confirm" }, question, yes, no));
  });
  wrap.append(button);
  return wrap;
}
const safeUrl = (url) => (/^https?:\/\//i.test(url || "") ? url : null);

function when(iso, withTime = true) {
  if (!iso) return "";
  const opts = { timeZone: "Asia/Jerusalem", day: "numeric", month: "numeric", year: "2-digit" };
  if (withTime) Object.assign(opts, { hour: "2-digit", minute: "2-digit" });
  return new Date(iso).toLocaleString("he-IL", opts);
}

// "gemini-3.8-flash" -> "3.8-flash"; the smallest fallback gets a warning (it ignores rules
// more easily -- the invented-names problem in 8.5 came from it).
const shortModel = (m) => (m || "").replace(/^gemini-/, "");
const weakModel = (m) => /lite/i.test(m || "");
function modelChip(label, model) {
  if (!model) return null;
  return el("span", { class: `chip${weakModel(model) ? " warn" : ""}`, dir: "ltr",
                      title: weakModel(model) ? "המודל החלש (גיבוי, כשהמכסה החינמית של החזקים נגמרה)" : "",
                      text: `${label}: ${shortModel(model)}${weakModel(model) ? " ⚠️" : ""}` });
}

function minutes(start, end) {
  if (!start || !end) return "";
  const m = Math.round((new Date(end) - new Date(start)) / 60000);
  return `${m} דק׳`;
}

async function api(path, body, method) {
  const res = await fetch(path, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${await idToken()}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status}`);
    err.status = res.status;
    err.detail = await res.json().then((j) => (typeof j.detail === "string" ? j.detail : ""), () => "");
    throw err;
  }
  return res.json();
}
const acct = (path) => `api/caregiver/${encodeURIComponent(account)}${path}`;

function status(text) { $("page-status").textContent = text || ""; }

// ---- sections ---------------------------------------------------------------------
function renderFlags(flags) {
  const open = flags.filter((f) => f.status === "open");
  if (!open.length) {
    $("flags").replaceChildren(p("✓ אין התראות פתוחות (התראות מופיעות כאן, למשל על ירידה פתאומית או מצוקה).", "flags-ok"));
    return;
  }
  $("flags").replaceChildren(...open.map((f) => el("div", { class: `flag ${f.severity}` },
    el("span", { class: "title", text: `⚠️ ${FLAG_KIND[f.kind] || f.kind}${f.severity === "high" ? " (חמור)" : ""} · ${when(f.created_at)}` }),
    ...flagBody(f),
    confirmButton("טופל", "לסמן שטופל?", async () => {
      try { await api(acct(`/flags/${encodeURIComponent(f.id)}/resolve`), {}); } catch { /* reload shows the truth */ }
      await loadAccount();
    }),
  )));
}

const ISSUE = { invented_fact: "המציאה עובדה", insisted: "התעקשה", wrong_language: "לא בעברית",
                cut_off: "קטעה אותו", early_goodbye: "סיימה מוקדם מדי", confusing_question: "שאלה מבלבלת",
                misheard: "שמעה לא נכון במשחק השמות", other: "אחר" };

// Each language on its own line: the English explanation, her words, his words -- never
// mixed in one line (bidirectional text is unreadable otherwise).
function flagBody(f) {
  const quote = (who, text) => text ? el("div", { class: "quote" },
    el("span", { class: "who", text: `${who}:` }), el("span", { dir: "rtl", text: `«${text}»` })) : null;
  if (f.tutor_said || f.he_said) {
    return [ISSUE[f.issue] ? p(`סוג: ${ISSUE[f.issue]}`, "muted kv") : null,
            quote("המטפלת", f.tutor_said), quote("הוא", f.he_said),
            f.evidence ? el("p", { class: "kv", dir: "ltr", text: f.evidence }) : null];
  }
  // older flags: one free-text line with "[kind] TUTOR: ... HIM: ..." -- split it into lines
  const m = /^\[(\w+)\]\s*(.*)$/s.exec(f.evidence || "");
  const body = m ? m[2] : f.evidence || "";
  const parts = body.split(/\s*(TUTOR:|HIM:)\s*/).filter(Boolean);
  if (parts.length < 2) return [p(f.evidence)];
  const lines = [m && ISSUE[m[1]] ? p(`סוג: ${ISSUE[m[1]]}`, "muted kv") : null];
  for (let i = 0; i < parts.length; i++) {
    if (parts[i] === "TUTOR:" || parts[i] === "HIM:") {
      lines.push(quote(parts[i] === "TUTOR:" ? "המטפלת" : "הוא", parts[i + 1] || ""));
      i++;
    } else {
      lines.push(p(parts[i]));
    }
  }
  return lines;
}

function probeChips(results) {
  if (!results?.length) return null;
  return el("div", { class: "probes" }, results.map((r) => el("span", {
    class: `probe ${r.result}`, dir: "auto",
    title: `${RESULT_TEXT[r.result] || r.result} · ${r.kind === "treated" ? "תורגל בעבר" : "חדש"}${r.low_confidence ? " · תמלול לא בטוח" : ""}`,
    text: `${RESULT[r.result] || "?"} ${r.word}${r.kind === "treated" ? "" : " (חדש)"}${r.low_confidence ? " ?" : ""}`,
  })));
}

// The names game in one session (12): its answers, or why it didn't happen.
function namesGameLine(s) {
  const g = s.names_game;
  if (!g && !s.probe_results?.length) return null;
  const head = el("b", { text: `משחק השמות${g ? ` (${GAME_STATUS[g.status] || g.status})` : ""}: ` });
  return el("div", { class: "kv" }, head, probeChips(s.probe_results) || "",
            g?.note ? el("span", { class: "muted", dir: "ltr", text: ` ${g.note}` }) : null);
}

// Steps mode (13): how far through the agenda the session got, and what she reported.
const STEP_KIND = { repetition: "תרגול חזרה", understanding: "תרגול הבנה", clarity: "תרגול בהירות",
                    area_probe: "משחק מדידה", story_probe: "סיפור לשחזר (מדידה)", his_view: "איך הוא מרגיש", summary: "סיכום במילים שלו", check: "היכרות: רגע של בדיקה", sequencing: "סיפור לפי סדר", opening: "פתיחה", conversation: "שיחה", names_game: "משחק השמות", practice: "תרגול",
                    activity: "פעילות", games_activity: "פעילות מהמשחקים", reserve: "רזרבה",
                    thread: "נושא לשיחה" };
const stepName = (a) => `${STEP_KIND[a.kind] || a.kind}${a.label ? ` ${a.label}` : ""}`;

// One step: its name, and when opened, the exact instruction she got (English) -- plus her report.
function stepItem(a, i, report) {
  const mark = report === undefined ? "" : report ? "✓ " : "· ";
  return el("details", { class: "step" },
    el("summary", { text: `${mark}${i + 1}. ${stepName(a)}` }),
    a.text ? el("p", { class: "muted kv", dir: "ltr", text: a.text }) : null,
    report ? el("p", { class: "kv", dir: "ltr",
      text: `Her report (${Math.round(report.at_s / 6) / 10} min): ${report.done}${report.how_it_went ? ` — ${report.how_it_went}` : ""}` })
      : null);
}

function stepsLine(s) {
  if (!s.agenda?.length) return null;
  const done = s.steps_done || [];
  const extra = done.slice(s.agenda.length); // reports after the planned steps (open threads)
  return el("details", { class: "kv" },
    el("summary", { text: `שלבים: ${Math.min(done.length, s.agenda.length)} מתוך ${s.agenda.length}` +
                          ` (${s.agenda.map((a, i) => `${i < done.length ? "✓" : "·"} ${stepName(a)}`).join(" · ")})` }),
    ...s.agenda.map((a, i) => stepItem(a, i, done[i] || null)),
    s.agenda_after ? el("details", { class: "step" }, el("summary", { text: "אחרי השלבים: שאלת המשך, שוב ושוב עד הודעת הסיום" }),
                        el("p", { class: "muted kv", dir: "ltr", text: s.agenda_after })) : null,
    ...extra.map((d) => el("p", { class: "muted kv", dir: "ltr",
      text: `${Math.round(d.at_s / 6) / 10} min · ${d.done}${d.how_it_went ? ` — ${d.how_it_went}` : ""}` })),
    heldLine(s));
}

// Where she tried to move on and the app held her (13.10): after a question, or too few answers.
const HELD_WHY = { question: "אחרי ששאלה שאלה", answers: "לפני שענה מספיק" };
function heldLine(s) {
  const held = s.steps_held || [];
  if (!held.length) return null;
  return p("ניסתה לעבור שלב מוקדם (נעצרה): " + held.map((h) =>
    `שלב ${h.step + 1}, ${HELD_WHY[h.reason] || h.reason}, דקה ${Math.round(h.at_s / 6) / 10}`).join(" · "), "muted kv");
}

// The steps the next session would run (13), shown under the next lesson.
function nextSteps(plan) {
  if (!plan.steps?.length) return null;
  return el("details", { class: "kv" },
    el("summary", { text: `השלבים לשיחה הבאה (${plan.steps.length})` +
                          (plan.estimated_minutes ? ` · כ־${Math.round(plan.estimated_minutes)} דקות בקצב שלו` : "") }),
    ...plan.steps.map((a, i) => stepItem(a, i)),
    el("details", { class: "step" }, el("summary", { text: "אחרי השלבים: שאלת המשך, שוב ושוב עד הודעת הסיום" }),
       el("p", { class: "muted kv", dir: "ltr", text: plan.steps_after || "" })));
}

// Telling things in order (14): the task and its score.
const SEQ_TASK = { scrambled: "מעורבב", retell: "שחזור סיפור" };
function sequencingLine(s) {
  const q = s.sequencing;
  if (!q) return null;
  const head = `סיפור לפי סדר (${SEQ_TASK[q.task] || q.task}, ${q.events} אירועים${q.title ? `, ${q.title}` : ""}): `;
  if (q.status === "skipped") return p(`${head}דולג${q.note ? ` (${q.note})` : ""}`, "kv muted");
  if (q.status !== "done") return p(`${head}לא דווח`, "kv muted");
  return p(`${head}${q.order_pct}% בסדר הנכון · ${q.events_included} מתוך ${q.events} אירועים · ` +
           `${q.needed_help ? "עם עזרה" : "בלי עזרה"}${q.low_confidence ? " · תמלול לא בטוח" : ""}`, "kv");
}

// A short text in his own words (17): how many of its main ideas he conveyed.
function summarizingLine(s) {
  const q = s.summarizing;
  if (!q) return null;
  const head = `סיכום במילים שלו (${q.ideas} רעיונות${q.title ? `, ${q.title}` : ""}): `;
  if (q.status === "skipped") return p(`${head}דולג${q.note ? ` (${q.note})` : ""}`, "kv muted");
  if (q.status !== "done") return p(`${head}לא דווח`, "kv muted");
  return p(`${head}${q.ideas_conveyed} מתוך ${q.ideas} (${q.ideas_pct}%) · ${q.needed_help ? "עם עזרה" : "בלי עזרה"}` +
           `${q.low_confidence ? " · תמלול לא בטוח" : ""}`, "kv");
}

// Names he went for on his own in free talk (12): found / couldn't find.
function ownNamesLine(s) {
  const own = s.own_names || [];
  if (!own.length) return null;
  const names = (result) => own.filter((o) => o.result === result).map((o) => `${o.word}${o.low_confidence ? " ?" : ""}`);
  const found = names("self_found"), missed = names("not_found");
  return p([found.length ? `★ מצא לבד: ${found.join(", ")}` : "", missed.length ? `… לא מצא: ${missed.join(", ")}` : ""]
    .filter(Boolean).join(" · "), "kv");
}

function renderTranscript(box, turns) {
  if (!turns.length) {
    box.replaceChildren(p("אין תמלול לשיחה הזו.", "muted"));
    return;
  }
  box.replaceChildren(...turns.map((t) => {
    const mine = t.speaker !== "tutor";
    const main = t.text || t.live_text || "";
    const alt = mine && t.live_text && t.text && t.live_text.trim() !== t.text.trim() ? t.live_text : "";
    return el("div", { class: `turn ${mine ? "patient" : "tutor"}`, dir: "auto" },
      el("b", { text: mine ? "הוא: " : "המטפלת: " }), main || "(ריק)",
      alt ? el("span", { class: "alt", text: `כתוביות הדפדפן: ${alt}` }) : null);
  }));
}

// Leaving a conversation out (20.5): nothing that learns reads it; it stays here, marked, and can come back.
async function rebuildAfterLeaveOut() {
  try { await api(acct("/plan/rebuild"), {}); return true; } catch { return false; }
}

function leaveOutControl(s) {
  const sid = encodeURIComponent(s.id);
  if (s.excluded) {
    return confirmButton("↩ להחזיר", "להחזיר את השיחה לזיכרון ולתכנון?", async (where) => {
      busy(where, "מחזיר");
      try {
        const r = await api(acct(`/sessions/${sid}/put-back`), { restored_away: !!s.memory_restored_away });
        if (r.process) {
          busy(where, "השיחה תעובד מחדש: זיכרון, הגדרות קול והשיעור הבא. זה עשוי לקחת עד 2–3 דקות");
          await api(acct(`/sessions/${sid}/process`), {}).catch(() => null);
        }
        await loadAccount();
        status(r.process ? "✓ השיחה הוחזרה ועובדה מחדש." : "✓ השיחה הוחזרה: הסיכום ותוצאות משחק השמות שלה חזרו.");
      } catch {
        where.textContent = "ההחזרה נכשלה. נסה שוב.";
      }
    });
  }
  return confirmButton("🚫 לא לכלול בזיכרון ובתכנון",
    "לא ללמוד מהשיחה הזו? היא תישאר כאן, מסומנת, ואפשר להחזיר אותה.", async (where) => {
      busy(where, "מוציא את השיחה");
      let r;
      try {
        r = await api(acct(`/sessions/${sid}/leave-out`), {});
      } catch (err) {
        where.textContent = err.status === 409 ? "הזיכרון מתעדכן מהשיחה הזו ממש עכשיו. נסה שוב בעוד דקה." : "הפעולה נכשלה. נסה שוב.";
        return;
      }
      const finish = async (note) => {
        if (r.rebuild) busy(where, "בונה מחדש את השיעור הבא, בלי השיחה הזו");
        const rebuilt = r.rebuild ? await rebuildAfterLeaveOut() : true;
        await loadAccount();
        status(["✓ השיחה לא נכללת יותר.", note, rebuilt ? "" : "בניית השיעור הבא מחדש נכשלה: אפשר ללחוץ \"בנייה מחדש\"."]
          .filter(Boolean).join(" "));
      };
      if (r.is_latest) { // the latest processed conversation: an exact restore is possible
        const yes = el("button", { class: "yes", type: "button", text: "כן, להחזיר" });
        const no = el("button", { type: "button", text: "לא" });
        yes.addEventListener("click", async () => {
          yes.disabled = no.disabled = true;
          busy(where, "מחזיר את הזיכרון");
          try { await api(acct("/memory/restore"), { version: s.id }); } catch { status("החזרת הזיכרון נכשלה."); }
          await finish("הזיכרון הוחזר למצב שלפני השיחה.");
        });
        no.addEventListener("click", async () => { yes.disabled = no.disabled = true; await finish(""); });
        where.replaceChildren(el("span", { class: "confirm" }, "גם להחזיר את הזיכרון למצב שלפני השיחה?", yes, no));
        return;
      }
      await finish(r.was_processed ? "שיחות מאוחרות יותר כבר נלמדו -- פריטים מהשיחה הזו אפשר להסיר אחד אחד בזיכרון." : "");
    });
}

function renderSessions(sessions) {
  if (!sessions.length) {
    $("sessions").replaceChildren(p("עדיין אין שיחות בחשבון הזה.", "muted"));
    return;
  }
  $("sessions").replaceChildren(...sessions.map((s) => {
    const box = el("div", { class: "transcript", hidden: true });
    const button = el("button", { class: "small", type: "button", text: "תמלול מלא" });
    button.addEventListener("click", async () => {
      if (!box.hidden) { box.hidden = true; button.textContent = "תמלול מלא"; return; }
      box.hidden = false;
      button.textContent = "הסתרת התמלול";
      box.replaceChildren(p("טוען…", "muted"));
      try {
        renderTranscript(box, (await api(acct(`/sessions/${encodeURIComponent(s.id)}`))).turns);
      } catch {
        box.replaceChildren(p("טעינת התמלול נכשלה.", "muted"));
      }
    });
    const promptBox = el("div", { hidden: true });
    const promptButton = el("button", { class: "small", type: "button", text: "הפרומפט" });
    promptButton.addEventListener("click", async () => {
      if (!promptBox.hidden) { promptBox.hidden = true; promptButton.textContent = "הפרומפט"; return; }
      promptBox.hidden = false;
      promptButton.textContent = "הסתרת הפרומפט";
      busy(promptBox, "טוען");
      try {
        const data = await api(acct(`/sessions/${encodeURIComponent(s.id)}/prompt`));
        promptBox.replaceChildren(data.text
          ? el("pre", { class: "plan prompt", dir: "auto", text: data.text })
          : p("הפרומפט של השיחה הזו לא נשמר (נשמר רק לשיחות מ־8.5 והלאה). עותק שמור 30 יום בדלי הפרטי.", "muted"));
      } catch {
        promptBox.replaceChildren(p("טעינת הפרומפט נכשלה.", "muted"));
      }
    });
    // Not processed yet (memory update or next lesson missing/failed, or a tab closed mid-session):
    // process it now instead of waiting for the hourly sweep.
    const unprocessed = !s.excluded && ( // a left-out one (20.5) isn't processed
      (s.status === "active" && s.started_at && Date.now() - new Date(s.started_at) > 20 * 60000)
      || (s.status === "ended" && ["pending", "failed", "processing"].includes(s.memory_status))
      || (s.memory_status === "done" && ["pending", "failed"].includes(s.plan_status)));
    // Picks up where it stopped: if only the next lesson is missing, only that runs.
    const onlyPlan = s.memory_status === "done";
    const processButton = unprocessed ? confirmButton(
      onlyPlan ? "⚙️ בניית השיעור הבא עכשיו" : "⚙️ עיבוד השיחה עכשיו",
      onlyPlan ? "הזיכרון כבר עודכן. לבנות עכשיו רק את השיעור הבא?" : "לעבד עכשיו (זיכרון, הגדרות קול ושיעור הבא)?",
      async (where) => {
        busy(where, "מעבד את השיחה: זיכרון, הגדרות קול והשיעור הבא. זה עשוי לקחת עד 2–3 דקות");
        try {
          const r = await api(acct(`/sessions/${encodeURIComponent(s.id)}/process`), {});
          await loadAccount();
          status(r.memory_status === "not_claimed"
            ? "השיחה כבר בעיבוד (או שעובדה בינתיים). רענן בעוד דקה."
            : r.memory_status === "failed" || r.plan_status === "failed"
              ? `העיבוד לא הצליח (המודלים עמוסים?). אפשר לנסות שוב בעוד כמה דקות. ${r.error ? `(${r.error.slice(0, 120)})` : ""}`
              : "✓ השיחה עובדה: הזיכרון עודכן והשיעור הבא נבנה.");
        } catch (err) {
          where.textContent = err.status === 409 ? "נראה שהשיחה עוד פעילה." : "העיבוד נכשל. נסה שוב.";
        }
      }) : null;
    const problems = [s.memory_status === "failed" && "עדכון הזיכרון נכשל", s.plan_status === "failed" && "בניית השיעור נכשלה",
                      s.goodbye_refusals > 0 && `⚠ סירוב פרידה ×${s.goodbye_refusals}`] // a goodbye that looped (20)
      .filter(Boolean);
    return el("div", { class: s.excluded ? "session left-out" : "session" },
      el("div", { class: "head" },
        el("span", { class: "when", text: when(s.started_at) }),
        el("span", { class: "muted", text: [minutes(s.started_at, s.ended_at), `${s.turn_count || 0} תורות`,
                                            END_REASON[s.end_reason] || s.end_reason || (s.status === "active" ? "פעילה" : "")]
                                            .filter(Boolean).join(" · ") }),
        s.plan_goal ? el("span", { class: "chip", text: GOAL[s.plan_goal] || s.plan_goal }) : null,
        s.plan_type === "intro" ? el("span", { class: "chip", text: "היכרות" }) : null,
        s.excluded ? el("span", { class: "chip warn", text: "לא נכלל" }) : null,
        MOOD[s.mood] ? el("span", { class: "chip", text: MOOD[s.mood] }) : null,
        modelChip("memory", s.memory_model), modelChip("plan", s.plan_model),
        ...problems.map((t) => el("span", { class: "chip warn", text: t })),
      ),
      s.summary ? p(s.summary) : p(s.memory_status === "done" ? "" : "עדיין אין סיכום לשיחה הזו.", "muted"),
      s.highlights?.length ? p(`הצלחות: ${s.highlights.join(" · ")}`) : null,
      s.difficulties?.length ? p(`קשיים: ${s.difficulties.join(" · ")}`) : null,
      namesGameLine(s),
      ownNamesLine(s),
      sequencingLine(s),
      summarizingLine(s),
      stepsLine(s),
      voiceLine(s),
      // The transcript stays one click away; the rest is in one "⋯" menu (21).
      el("div", { class: "cg-actions" }, button,
        el("details", { class: "more-menu" }, el("summary", { "aria-label": "עוד פעולות", text: "⋯" }),
          el("div", { class: "menu" }, promptButton, recordingButton(s), processButton, leaveOutControl(s)))),
      box, promptBox,
    );
  }));
}

function renderPlan(plan, notes) {
  const r = plan.research;
  const research = !r ? "לא הופעל (אין מפתח, אין תקציב, או שיעור ישן)."
    : r.status === "not_needed" ? `לא נדרש: ${r.reason || ""}`
    : `${r.status}: "${r.question || ""}"${r.techniques?.length ? ` → ${r.techniques.join(", ")}` : ""}`;
  $("plan").replaceChildren(
    plan.rendered
      ? el("pre", { class: "plan", dir: "auto", text: plan.rendered })
      : p("אין תוכנית שמורה: המטפלת תעקוב אחרי המבנה הכללי.", "muted"),
    plan.built_at ? p(`נבנה: ${when(plan.built_at)} · גרסת הנחיות ${plan.prompt_version || "?"}`, "muted kv") : null,
    plan.model ? el("p", { class: "kv" }, "נבנה על ידי: ", modelChip("model", plan.model),
                    weakModel(plan.model) ? " המודל החלש. כדאי לבנות מחדש כשהמכסה מתחדשת (או אחרי המעבר לגרסה בתשלום)." : "")
               : null,
    p(`מחקר: ${research}`, "kv"),
    notesLine(plan, notes),
    nextSteps(plan),
  );
}

// Did this plan see the current planner notes? (recorded by the code when the plan was built)
function notesLine(plan, notes) {
  const hasNotes = !!notes?.text?.trim();
  if (!hasNotes) return null;
  const usedAt = plan.notes_used_at ? new Date(plan.notes_used_at).getTime() : 0;
  const savedAt = notes.updated_at ? new Date(notes.updated_at).getTime() : 0;
  if (!plan.built_at || !usedAt || savedAt > usedAt) {
    return p("⚠️ ההערות לבונה השיעורים השתנו אחרי שהשיעור הזה נבנה. לחץ \"לבנות מחדש\" כדי להחיל אותן.", "kv plan-warning");
  }
  return el("div", {},
    p(`✓ נבנה עם ההערות שנשמרו ב־${when(notes.updated_at)}.`, "kv"),
    plan.notes_applied ? p(`איך בונה השיעורים יישם אותן (לפי דבריו): ${plan.notes_applied}`, "kv muted") : null);
}

function sectionLists(sections, editable = false) {
  return Object.entries(SECTION).map(([key, title]) => {
    const items = sections?.[key] || [];
    if (!items.length && !editable) return null;
    return el("div", {}, el("h3", { text: title }), el("ul", {}, items.map((item) => el("li", {},
      el("span", { class: "mem-item" }, el("span", { dir: "auto", text: item }),
        editable ? inlineEditor("✎", item, (text, where) =>
          memoryEdit("/memory/edit-item", { section: key, old: item, new: text }, where, "✓ הפריט עודכן.")) : null,
        editable ? confirmButton("✕", "להסיר את הפריט (גם מהסיכום)?", (wrap) => removeItem(key, item, wrap), "x") : null)))),
      editable ? inlineEditor("+ הוספה", "", (text, where) =>
        memoryEdit("/memory/add-item", { section: key, text }, where, "✓ הפריט נוסף."), "add") : null);
  });
}

// Editing the memory (21): an inline text box under the clicked button, with save / cancel.
function inlineEditor(label, initial, save, cls = "x") {
  const wrap = el("span", {});
  const button = el("button", { class: cls, type: "button", text: label });
  button.addEventListener("click", () => {
    const box = el("input", { type: "text", dir: "auto", value: initial, maxlength: 1500, class: "mem-input" });
    box.value = initial;
    const ok = el("button", { class: "yes", type: "button", text: "שמירה" });
    const no = el("button", { type: "button", text: "ביטול" });
    no.addEventListener("click", () => wrap.replaceChildren(button));
    const go = async () => { ok.disabled = no.disabled = true; await save(box.value, wrap); };
    ok.addEventListener("click", go);
    box.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); if (e.key === "Escape") no.click(); });
    wrap.replaceChildren(el("span", { class: "confirm" }, box, ok, no));
    box.focus();
  });
  wrap.append(button);
  return wrap;
}

// Free text in the memory (21): the shown block with an edit button that swaps it for a text box.
function textEditor(view, initial, hint, save) {
  const wrap = el("div", {});
  const show = () => {
    const button = el("button", { class: "add", type: "button", text: "✎ עריכה" });
    button.addEventListener("click", () => {
      const box = el("textarea", { dir: "auto", class: "mem-text", rows: Math.min(24, initial.split("\n").length + 2) });
      box.value = initial;
      const ok = el("button", { class: "yes", type: "button", text: "שמירה" });
      const no = el("button", { type: "button", text: "ביטול" });
      const status = el("span", { class: "muted" });
      no.addEventListener("click", show);
      ok.addEventListener("click", async () => { ok.disabled = no.disabled = true; await save(box.value, status); ok.disabled = no.disabled = false; });
      wrap.replaceChildren(p(hint, "muted kv"), box, el("div", { class: "confirm" }, ok, no, status));
      box.focus();
    });
    wrap.replaceChildren(view, button);
  };
  show();
  return wrap;
}

// Every memory edit: saved at once (no model), the previous version kept in the versions list.
async function memoryEdit(path, body, where, okText) {
  busy(where, "שומר");
  try {
    await api(acct(path), body);
    await loadAccount();
    $("memory-status").textContent = `${okText} הגרסה הקודמת נשמרה ברשימת הגרסאות. נכנס לתוקף מהשיחה הבאה.`;
  } catch (err) {
    const msg = err.status === 409 ? "הזיכרון השתנה בינתיים (או שהפריט כבר קיים). רענן ונסה שוב."
      : err.status === 422 && path === "/memory/edit-text" ? (err.detail?.startsWith("lines outside")
        ? `יש שורות שאינן תחת כותרת או שלא מתחילות ב־"- ", והן היו הולכות לאיבוד: ${err.detail.split(": ").slice(1).join(": ")}`
        : "פריט ארוך מדי (עד 200 תווים), יותר מ־25 פריטים תחת כותרת, או סיכום ריק. שום דבר לא השתנה.")
      : err.status === 422 && path === "/memory/edit-focus" ? "עד 4 דגשים, ועד 200 תווים בכל שורה."
      : err.status === 422 ? "הטקסט ריק, ארוך מדי, או שהקטע מלא (25 פריטים). כדי למחוק, השתמש ב־✕."
      : "השמירה לא הצליחה, ושום דבר לא השתנה. נסה שוב בעוד רגע.";
    where.textContent = msg;
    $("memory-status").textContent = msg;
  }
}

// The last session summaries she knows (the newest is her "Last time" line): fix or remove one (21).
function summariesList(recent) {
  if (!recent?.length) return null;
  return el("div", {}, el("h3", { text: "שיחות אחרונות (מה היא זוכרת מהן)" }),
    el("ul", {}, recent.slice().reverse().map((r) => el("li", {},
      el("span", { class: "mem-item" }, el("span", { dir: "auto", text: `${r.date}: ${r.summary}` }),
        inlineEditor("✎", r.summary, (text, where) =>
          memoryEdit("/memory/edit-summary", { date: r.date, old: r.summary, new: text }, where, "✓ הסיכום עודכן.")),
        confirmButton("✕", "להסיר את הסיכום הזה מהזיכרון שלה?", (wrap) =>
          memoryEdit("/memory/remove-summary", { date: r.date, old: r.summary }, wrap, "✓ הסיכום הוסר."), "x"))))));
}

// His names and places, in the profile she reads (21). A removed word is blocked: the app never adds it back.
function vocabularyBlock(profile) {
  const head = el("h3", { text: "שמות ומקומות שלו (בפרופיל)" });
  if (!profile?.source) return null;
  if (profile.source === "uploaded") {
    return el("div", {}, head, p("הפרופיל הועלה על ידכם: השמות באים מהשורה \"Vocabulary:\" שבו, ועורכים אותם בכרטיס הפרופיל.", "muted kv"));
  }
  const vocab = profile.vocabulary || [], blocked = profile.vocabulary_blocked || [];
  const send = async (path, word, where, okText) => {
    busy(where, "שומר");
    try {
      await api(acct(path), { word });
      await loadAccount();
      $("memory-status").textContent = okText;
    } catch (err) {
      where.textContent = err.status === 422 ? "שם או מקום אחד, עד 40 תווים." : "השמירה נכשלה. רענן ונסה שוב.";
    }
  };
  return el("div", {}, head,
    el("div", { class: "vocab" }, vocab.length ? vocab.map((w) => el("span", { class: "vocab-word", dir: "auto" }, w,
      confirmButton("✕", "להסיר? האפליקציה לא תוסיף אותה שוב", (wrap) =>
        send("/vocabulary/remove", w, wrap, `✓ "${w}" הוסרה מהפרופיל, והאפליקציה לא תוסיף אותה שוב.`), "x")))
      : [p("אין עדיין.", "muted kv")]),
    inlineEditor("+ הוספת שם או מקום", "", (text, where) => send("/vocabulary/add", text, where, "✓ נוסף לפרופיל."), "add"),
    blocked.length ? el("div", { class: "vocab blocked" }, p("הוסרו (האפליקציה לא תוסיף אותן שוב):", "muted kv"),
      blocked.map((w) => el("span", { class: "vocab-word", dir: "auto" }, w,
        confirmButton("↩ להחזיר", "להחזיר לפרופיל?", (wrap) =>
          send("/vocabulary/add", w, wrap, `✓ "${w}" חזרה לפרופיל.`), "x")))) : null);
}

async function removeItem(section, item, where) {
  const text = "מוחק ומעדכן את הזיכרון, זה עשוי לקחת כמה שניות";
  busy(where, text); // next to the item that was clicked
  busy($("memory-status"), text); // and at the top of the memory section
  try {
    await api(acct("/memory/remove-item"), { section, item });
    await loadAccount();
    $("memory-status").textContent = "✓ הפריט הוסר, והסיכום של המטפלת עודכן בלעדיו. הגרסה הקודמת נשמרה ברשימת הגרסאות.";
  } catch (err) {
    const msg = err.status === 409
      ? "הזיכרון השתנה בינתיים. רענן ונסה שוב."
      : "ההסרה לא הצליחה, ושום דבר לא השתנה. נסה שוב בעוד רגע.";
    where.textContent = msg;
    $("memory-status").textContent = msg;
  }
}

function renderMemory(memory, profile) {
  if (!memory.memory_prompt) {
    $("memory").replaceChildren(p("אין זיכרון בחשבון הזה (השיחה הבאה תהיה פגישת היכרות).", "muted"));
    return;
  }
  $("memory").replaceChildren(
    p(`מבוסס על ${memory.sessions_processed || 0} שיחות · עודכן ${when(memory.updated_at)}`, "muted kv"),
    el("h3", { text: "מה המטפלת מקבלת בתחילת כל שיחה" }),
    textEditor(el("pre", { class: "plan", dir: "auto", text: memory.memory_prompt }), memory.memory_prompt,
      "כל שורה שמתחילה ב־\"- \" היא פריט, תחת הכותרת שלו (השורה העליונה היא החדשה). מחיקת כותרת מרוקנת את הקטע.",
      (text, where) => memoryEdit("/memory/edit-text", { old: memory.memory_prompt, text }, where, "✓ הטקסט עודכן.")),
    el("div", {}, el("h3", { text: "דגשים לשיחה הבאה" }),
      textEditor(memory.focus_next_session?.length
          ? el("ul", {}, memory.focus_next_session.map((f) => el("li", { dir: "auto", text: f })))
          : p("אין דגשים.", "muted kv"),
        (memory.focus_next_session || []).join("\n"), "דגש אחד בכל שורה, עד 4. השיחה הבאה תקבע דגשים חדשים.",
        (text, where) => memoryEdit("/memory/edit-focus", { items: text.split("\n") }, where, "✓ הדגשים עודכנו."))),
    ...sectionLists(memory.sections, true),
    summariesList(memory.recent_summaries),
    vocabularyBlock(profile),
  );
}

function versionKind(version) {
  if (version?.startsWith("edit-")) return " · לפני עריכה";
  if (version?.startsWith("restore-")) return " · לפני שחזור";
  return "";
}

async function loadHistory() {
  $("history").replaceChildren(p("טוען…", "muted"));
  try {
    const { versions } = await api(acct("/memory/history"));
    $("history").replaceChildren(...(versions.length ? versions.map((v) => el("details", { class: "version" },
      el("summary", { text: `${when(v.updated_at)} · ${v.sessions_processed || 0} שיחות${versionKind(v.version)}` }),
      confirmButton("שחזור הגרסה הזו", "להפוך אותה לזיכרון הנוכחי?", async (where) => {
        busy(where, "משחזר את הגרסה");
        busy($("memory-status"), "משחזר את הגרסה");
        try {
          await api(acct("/memory/restore"), { version: v.version });
          await loadAccount();
          $("memory-status").textContent = "הגרסה שוחזרה. הגרסה שהייתה נוכחית נשמרה ברשימה.";
        } catch {
          $("memory-status").textContent = "השחזור נכשל.";
        }
      }),
      el("pre", { class: "plan", dir: "auto", text: v.memory_prompt || "(ריק)" }),
      ...sectionLists(v.sections),
    )) : [p("אין גרסאות קודמות.", "muted")]));
  } catch {
    $("history").replaceChildren(p("הטעינה נכשלה.", "muted"));
  }
}

function renderWords(rows) {
  if (!rows.length) {
    $("words").replaceChildren(p("בנק המילים ריק.", "muted"));
    return;
  }
  const head = ["מילה", "מקור", "ניסיונות", "✓ לבד", "~ עם רמז", "✗", "★ / …", "תוצאה אחרונה", "הופיעה לאחרונה", "לתרגול שוב", ""];
  $("words").replaceChildren(el("div", { class: "table-wrap" }, el("table", { class: "words" },
    el("thead", {}, el("tr", {}, head.map((h) => el("th", { text: h })))),
    el("tbody", {}, rows.map((r) => el("tr", {},
      el("td", { dir: "auto", text: r.word }), el("td", { text: SOURCE[r.source || "practiced"] || r.source }),
      el("td", { text: r.attempts ?? 0 }), el("td", { text: r.uncued ?? 0 }),
      el("td", { text: r.cued ?? 0 }), el("td", { text: r.failed ?? 0 }),
      el("td", { text: `${r.self_found ?? 0} / ${r.not_found ?? 0}` }),
      el("td", { text: `${RESULT[r.last_result] || ""} ${RESULT_TEXT[r.last_result] || ""}${r.last_cue_level ? ` (${r.last_cue_level})` : ""}` }),
      el("td", { text: r.last_seen || "" }), el("td", { text: r.next_due || "" }),
      el("td", {}, confirmButton("✕", `להסיר את "${r.word}"?`, (where) => removeWord(r.word, where), "x")),
    ))),
  )));
}

// ---- the names game's set (12) ----------------------------------------------------------------
function renderNamesGame(current, history) {
  const box = $("names-game");
  const newSet = confirmButton("רשימה חדשה", "להחליף את רשימת השמות? הרשימה הנוכחית נשמרת להשוואה, ורשימה חדשה תיבנה בבנייה הבאה של השיעור.",
    async (where) => {
      busy(where, "מחליף");
      try {
        await api(acct("/check-in/new"), {});
        await loadAccount();
        $("names-game-status").textContent = "✓ הרשימה הוחלפה. רשימה חדשה תיבנה עם השיעור הבא (או לחץ \"לבנות מחדש\" בשיעור הבא).";
      } catch {
        where.textContent = "ההחלפה נכשלה. נסה שוב.";
      }
    });
  if (!current?.items?.length) {
    box.replaceChildren(p("עדיין אין רשימה. היא תיבנה עם השיעור הבא, ובינתיים אין משחק שמות.", "muted"),
      ...(history || []).slice(0, 1).map((h) => p(`הרשימה הקודמת (${h.created_on || ""}): ${(h.items || []).map((i) => i.target).join(", ")}`, "muted kv")));
    return;
  }
  const head = ["שם", "סוג", "השאלה", "נשאל", "תוצאות", ""];
  box.replaceChildren(
    p(`מאז ${current.created_on} · שוחק ב־${current.sessions_played || 0} שיחות${current.rationale ? ` · ` : ""}`, "kv"),
    current.rationale ? el("p", { class: "muted kv", dir: "ltr", text: current.rationale }) : null,
    el("div", { class: "table-wrap" }, el("table", { class: "words" },
      el("thead", {}, el("tr", {}, head.map((h) => el("th", { text: h })))),
      el("tbody", {}, current.items.map((i) => el("tr", {},
        el("td", { dir: "auto", text: i.target }),
        el("td", { text: i.kind === "treated" ? "תורגל" : "חדש" }),
        el("td", { dir: "auto", text: i.question }),
        el("td", { text: i.asked ?? 0 }),
        el("td", { text: (i.results || []).map((r) => RESULT[r.result] || "?").join(" ") }),
        el("td", {}, confirmButton("✕", `להוציא את "${i.target}" ממשחק השמות?`, (where) => removeGameName(i.target, where), "x")),
      ))))),
    el("div", { class: "cg-actions" }, newSet),
  );
}

async function removeGameName(target, where) {
  busy(where, "מוציא");
  try {
    await api(acct("/check-in/remove-item"), { target });
    await loadAccount();
    $("names-game-status").textContent = `✓ "${target}" הוצא ממשחק השמות.`;
  } catch {
    where.textContent = "ההוצאה נכשלה. נסה שוב.";
  }
}

async function removeWord(word, where) {
  busy(where, "מסיר");
  busy($("words-status"), `מסיר את "${word}" מבנק המילים`);
  try {
    await api(acct("/word-bank/remove"), { word });
    await loadAccount();
    $("words-status").textContent = `✓ "${word}" הוסרה מבנק המילים. הגרסה הקודמת נשמרה ברשימת הגרסאות של הזיכרון.`;
  } catch (err) {
    const msg = err.status === 409 ? "הזיכרון השתנה בינתיים. רענן ונסה שוב." : "ההסרה נכשלה. נסה שוב.";
    where.textContent = msg;
    $("words-status").textContent = msg;
  }
}

function renderResearch(notes) {
  if (!notes.length) {
    $("research").replaceChildren(p("עדיין אין ממצאי מחקר. בונה השיעורים מחפש רק כשהטכניקות המובנות לא מספיקות.", "muted"));
    return;
  }
  $("research").replaceChildren(...notes.map((n) => el("div", { class: "note" },
    p(`שאלה: ${n.question}`), n.created_at ? p(when(n.created_at), "muted kv") : null,
    p(n.summary),
    ...(n.techniques || []).map((t) => el("div", { class: "technique" },
      el("b", { dir: "auto", text: t.name }), p(t.how_to), p(t.hebrew_example),
      safeUrl(t.source_url)
        ? el("a", { href: safeUrl(t.source_url), target: "_blank", rel: "noopener noreferrer", dir: "ltr",
                    text: `${t.source_trusted ? "מקור מקצועי" : "אתר כללי"}: ${t.source_title || t.source_url}` })
        : null,
    )),
  )));
}

function renderGames(recs, profile) {
  if (!recs.length) {
    $("games").replaceChildren(p(profile ? "אין הצעות כרגע." : "לחשבון הזה אין פרופיל במשחקים.", "muted"));
    return;
  }
  $("games").replaceChildren(...recs.map((r) => el("div", { class: "rec" },
    el("div", { class: "head" }, el("b", { dir: "auto", text: r.title }), " ",
       el("span", { class: "chip", text: STATUS[r.status] || r.status }), " ",
       el("span", { class: "muted", text: `${r.game_id} · ${r.kind} · הוצע ${r.times_suggested || 1} פעמים` })),
    p(r.rationale), p(`נתונים: ${r.evidence}`, "muted"),
    el("div", { class: "buttons" },
      ...["accepted", "rejected", "done"].map((st) => {
        const b = el("button", { class: `small${r.status === st ? " on" : ""}`, type: "button", text: STATUS[st] });
        b.addEventListener("click", async () => {
          try { await api(acct(`/recommendations/${encodeURIComponent(r.id)}`), { status: r.status === st ? "new" : st }); } catch { /* reload */ }
          await loadAccount();
        });
        return b;
      }),
      safeUrl(r.github_url)
        ? el("a", { class: "small", href: r.github_url, target: "_blank", rel: "noopener noreferrer",
                    title: "נפתח טופס מוכן ב-GitHub. שום דבר לא נשלח עד שאתה לוחץ שם על Submit.",
                    text: "פתיחת issue ב-GitHub ↗" })
        : null,
    ),
  )));
}

// ---- the account's voice settings (09): summary at the top, editable in place ------------
const NOISE_NAME = { 0: "כבוי", 1: "עדין", 2: "בינוני", 3: "חזק" };
let voiceSaved = null;
let reminderSaved = null;
const DAY_NAMES = ["א׳", "ב׳", "ג׳", "ד׳", "ה׳", "ו׳", "ש׳"]; // Sunday = 0
$("reminder-hour").replaceChildren(...Array.from({ length: 24 }, (_, h) => new Option(`${String(h).padStart(2, "0")}:00`, String(h))));
$("reminder-days").replaceChildren(...DAY_NAMES.map((d, i) => el("label", { class: "day" },
  el("input", { type: "checkbox", value: String(i), class: "reminder-day" }), ` ${d}`)));

const REMINDER_STATUS = { sent: "נשלחה", skipped: "דולגה", failed: "לא נמסרה", test: "בדיקה" };
const REMINDER_REASON = { "already practised today": "כבר התאמן היום", "paused (spending soft stop)": "השימוש מושהה",
                          "not one of the chosen days": "יום שלא נבחר", "no device has reminders on": "אין מכשיר רשום" };

function reminderSummary(r) {
  if (!r) return null;
  const days = r.days?.length === 7 ? "כל יום" : (r.days || []).map((d) => DAY_NAMES[d]).join(" ");
  const last = r.history?.[0];
  return el("div", {},
    el("div", { class: "voice-facts" },
      el("span", {}, "🔔 תזכורת יומית: ", el("b", { text: r.enabled ? `${String(r.hour).padStart(2, "0")}:00, ${days}` : "כבויה" }),
         el("span", { class: "mode", text: ` (${r.devices} מכשירים רשומים)` })),
      r.devices ? confirmButton("שליחת תזכורת לבדיקה", "לשלוח עכשיו תזכורת למכשירים שלו?", async (where) => {
        busy(where, "שולח");
        try {
          const res = await api(acct("/reminder/test"), {});
          where.textContent = `✓ נשלחה ל־${res.devices} מכשירים`;
        } catch {
          where.textContent = "השליחה נכשלה.";
        }
      }) : null),
    last ? p(`אחרונה: ${when(last.at)} · ${REMINDER_STATUS[last.status] || last.status}` +
             (last.reason ? ` (${REMINDER_REASON[last.reason] || last.reason})` : ""), "muted kv") : null);
}

function fillReminderForm(r) {
  reminderSaved = r;
  $("reminder-on").checked = !!r?.enabled;
  $("reminder-hour").value = String(r?.hour ?? 10);
  const days = new Set(r?.days ?? [0, 1, 2, 3, 4, 5, 6]);
  document.querySelectorAll(".reminder-day").forEach((c) => { c.checked = days.has(Number(c.value)); });
}
let audioUsage = ""; // "34 קבצים, 68MB" -- this account's stored recordings

// "noise filter 0 -> 1 (2 noise interruptions)" -> Hebrew, for the page
function changeText(c) {
  return c.replace(/^silence (\S+)s -> (\S+)s/, "שקט $1 → $2 שניות").replace(/^noise filter (\d) -> (\d)/, "מסנן רעשים $1 → $2")
    .replace(/\((\d+) cut-offs\)/, "($1 קטיעות)").replace(/\((\d+) noise interruptions\)/, "($1 הפרעות רעש)")
    .replace(/\(3 sessions without cut-offs\)/, "(3 שיחות בלי קטיעות)")
    .replace(/\(3 sessions without noise interruptions\)/, "(3 שיחות בלי הפרעות רעש)");
}

function renderVoice(v) {
  voiceSaved = v;
  const last = v.auto_state?.last;
  const fact = (label, value, auto) => el("span", {}, `${label}: `, el("b", { text: value }),
                                          el("span", { class: "mode", text: auto ? " (אוטומטי)" : " (קבוע)" }));
  $("voice-summary").replaceChildren(
    el("div", { class: "voice-facts" },
      v.tap_to_talk ? el("span", {}, el("b", { text: "לחיצה לדיבור פעילה" }), el("span", { class: "mode", text: " (השקט והמסנן לא חלים)" }))
                    : null,
      fact("שקט לפני שהיא עונה", silenceText(v.silence_ms), v.silence_auto),
      fact("מסנן רעשים", `${v.noise_level} · ${NOISE_NAME[v.noise_level]}`, v.noise_auto),
      v.tap_to_talk ? null : el("span", {}, "לחיצה לדיבור: ", el("b", { text: "כבויה" })),
      el("span", {}, "הקלטה: ", el("b", { text: v.record_audio === false ? "כבויה" : "פועלת" }),
         audioUsage ? el("span", { class: "mode", text: ` (${audioUsage})` }) : null)),
    last ? p(`החלטה אוטומטית אחרונה (${when(last.at)}): ${last.changes?.length ? last.changes.map(changeText).join(" · ") : "ללא שינוי"}` +
             ` · נמדדו ${last.measured?.cut_offs ?? 0} קטיעות, ${last.measured?.noise_interruptions ?? 0} הפרעות רעש`, "muted kv")
         : p("עדיין אין החלטות אוטומטיות (הן מתחילות אחרי השיחה הבאה).", "muted kv"),
    v.auto_state?.suggest_tap_to_talk
      ? p("💡 הפרעות רעש נמשכות גם במסנן החזק ביותר. כדאי לשקול להפעיל \"לחיצה לדיבור\".", "suggest") : null,
  );
  fillVoiceForm(v);
}

// 0 = no silence length set: Gemini decides on its own when he finished speaking.
const silenceText = (ms) => (ms ? `${ms / 1000} שניות` : "0 · Gemini מחליט לבד");
function showSilenceValue() {
  $("silence-value").textContent = silenceText(Number($("silence").value) * 1000);
}

function fillVoiceForm(v) {
  $("silence-mode").value = v.silence_auto ? "auto" : "fixed";
  $("silence").value = v.silence_ms / 1000;
  showSilenceValue();
  $("noise-mode").value = v.noise_auto ? "auto" : "fixed";
  $("noise-level").value = String(v.noise_level);
  $("tap-to-talk").checked = !!v.tap_to_talk;
  $("record-audio").checked = v.record_audio !== false;
  $("voice-status").textContent = "";
}

$("voice-edit").addEventListener("click", () => { $("voice-form").hidden = !$("voice-form").hidden; });
$("voice-cancel").addEventListener("click", () => { fillVoiceForm(voiceSaved); fillReminderForm(reminderSaved); $("voice-form").hidden = true; });
$("silence").addEventListener("input", showSilenceValue);
$("voice-save").addEventListener("click", async () => {
  $("voice-save").disabled = true;
  try {
    await api(acct("/settings"), { voice: {
      silence_ms: Math.round(Number($("silence").value) * 1000), silence_auto: $("silence-mode").value === "auto",
      noise_level: Number($("noise-level").value), noise_auto: $("noise-mode").value === "auto",
      tap_to_talk: $("tap-to-talk").checked, record_audio: $("record-audio").checked } }, "PUT");
    await api(acct("/reminder"), { reminder: {
      enabled: $("reminder-on").checked, hour: Number($("reminder-hour").value),
      days: [...document.querySelectorAll(".reminder-day")].filter((c) => c.checked).map((c) => Number(c.value)) } }, "PUT");
    await loadAccount();
    $("voice-form").hidden = true;
    $("voice-status").textContent = "";
    $("voice-summary").prepend(p("✓ נשמר. יחול מהשיחה הבאה.", "kv"));
  } catch {
    $("voice-status").textContent = "השמירה נכשלה.";
  } finally {
    $("voice-save").disabled = false;
  }
});

// The session's recording (09): fetched with sign-in, then played here. Caregivers only.
function recordingButton(s) {
  if (!s.audio_bytes) return null;
  const wrap = el("span", {});
  const button = el("button", { class: "small", type: "button",
                                text: `🔊 הקלטה (${Math.max(1, Math.round(s.audio_bytes / 1024))}KB)` });
  button.addEventListener("click", async () => {
    busy(wrap, "טוען את ההקלטה");
    try {
      const res = await fetch(acct(`/sessions/${encodeURIComponent(s.id)}/audio`),
                              { headers: { Authorization: `Bearer ${await idToken()}` } });
      if (!res.ok) throw new Error(res.status === 404 ? "ההקלטה כבר לא שמורה (נמחקת אחרי 90 יום)." : `HTTP ${res.status}`);
      const player = el("audio", { controls: true, preload: "auto", class: "player" });
      player.src = URL.createObjectURL(await res.blob());
      wrap.replaceChildren(player);
      player.play().catch(() => {});
    } catch (err) {
      wrap.replaceChildren(el("span", { class: "muted", text: err.message.startsWith("HTTP") ? "טעינת ההקלטה נכשלה." : err.message }));
    }
  });
  wrap.append(button);
  return wrap;
}

// One line per session: what it ran with, what was measured, what changed after it.
function voiceLine(s) {
  const u = s.voice_used, d = s.voice_decision;
  if (!u && !d) return null;
  const parts = [];
  if (u) parts.push(u.tap_to_talk ? "לחיצה לדיבור" : `שקט ${u.silence_ms ? `${u.silence_ms / 1000} ש׳` : "לפי Gemini"} · מסנן ${u.noise_level}`);
  if (d?.measured) parts.push(`קטיעות ${d.measured.cut_offs} · הפרעות רעש ${d.measured.noise_interruptions}`);
  if (d?.changes?.length) parts.push(`→ ${d.changes.map(changeText).join(" · ")}`);
  else if (d?.measured) parts.push("→ ללא שינוי");
  return el("p", { class: "voice-line", text: `🎚️ ${parts.join(" · ")}` });
}

// His profile (15): uploaded here, or inferred by the app from his first sessions (15.5).
const PROFILE_SOURCE = { uploaded: "נכתב כאן", inferred: "נבנה ע\"י האפליקציה מהשיחות" };
let savedProfile = "";
function renderProfile(profile) {
  savedProfile = profile?.text || "";
  $("profile-source").textContent = savedProfile
    ? `מקור: ${PROFILE_SOURCE[profile.source] || profile.source} · עודכן ${when(profile.updated_at)}`
    : "אין פרופיל לחשבון הזה: המטפלת מכירה אותו רק מהשיחות.";
  if (profile?.source === "inferred") {
    $("profile-source").textContent += " · האפליקציה מעדכנת אותו אחרי כל שיחה; עריכה כאן הופכת אותו לשלכם, והיא תפסיק לעדכן.";
  }
  $("profile-view").textContent = savedProfile;
  $("profile-view").hidden = !savedProfile;
  $("profile-status").textContent = "";
  editProfile(false);
}
// Read-only like the prompt and memory cards; the editor opens on demand.
function editProfile(on) {
  $("profile").value = savedProfile;
  for (const id of ["profile-edit", "profile-save", "profile-load", "profile-count"]) $(id).hidden = !on;
  $("profile-view").hidden = on || !savedProfile;
  $("profile-toggle").textContent = on ? "ביטול" : savedProfile ? "עריכה" : "הוספת פרופיל";
  if (on) countProfile();
}
$("profile-toggle").addEventListener("click", () => {
  editProfile($("profile-edit").hidden);
  $("profile-status").textContent = "";
});
function countProfile() { $("profile-count").textContent = `${$("profile").value.length}/8000`; }
$("profile").addEventListener("input", () => { countProfile(); $("profile-status").textContent = "לא נשמר"; });
$("profile-file").addEventListener("change", async () => {
  const file = $("profile-file").files[0];
  if (!file) return;
  $("profile").value = (await file.text()).slice(0, 8000);
  countProfile();
  $("profile-status").textContent = `נטען "${file.name}" -- לא נשמר עדיין`;
  $("profile-file").value = "";
});
$("profile-save").addEventListener("click", async () => {
  $("profile-save").disabled = true;
  try {
    await api(acct("/profile"), { text: $("profile").value }, "PUT");
    await loadAccount();
    $("profile-status").textContent = "✓ נשמר. הגרסה הקודמת גובתה. נכנס לתוקף מהשיחה הבאה.";
  } catch {
    $("profile-status").textContent = "השמירה נכשלה.";
  } finally {
    $("profile-save").disabled = false;
  }
});

// His needs per area (15.5): inferred from his first sessions, or set by the family (which wins).
const NEED_AREA = { conversation: "שיחה (שטף, מציאת מילים)", naming: "שיום (מציאת שמות ומילים)",
                    repetition: "חזרה אחריה", understanding: "הבנה",
                    connected_speech: "דיבור רציף (הסבר, סיפור לפי סדר)", clarity: "בהירות הדיבור",
                    goals: "המטרות שלו" };
const NEED_LEVEL = { ok: "בסדר", some_difficulty: "קושי מסוים", clear_difficulty: "קושי ברור",
                     unclear: "לא ברור עדיין" };
const NOT_PRACTICED = new Set(["repetition", "understanding", "clarity"]);
function renderNeeds(needs) {
  const areas = needs?.areas || {};
  $("needs").replaceChildren(...Object.entries(NEED_AREA).map(([area, name]) => {
    const a = areas[area] || {};
    const level = area === "goals" ? null : el("select", { "aria-label": name },
      el("option", { value: "", text: "—" }),
      ...Object.entries(NEED_LEVEL).map(([v, t]) => {
        const o = el("option", { value: v, text: t });
        if (a.level === v) o.selected = true;
        return o;
      }));
    const note = el("input", { type: "text", maxlength: "300", dir: "auto", value: a.note || "",
                               placeholder: area === "goals" ? "מה הוא רוצה להצליח לעשות" : "הערה (למשל מהקלינאית)" });
    const save = el("button", { class: "small", type: "button", text: "שמירה" });
    save.addEventListener("click", () => saveNeed(area, level?.value || "", note.value, save));
    const who = a.set_by === "family" ? "המשפחה" : a.set_by === "app" ? `האפליקציה${a.date ? `, ${a.date}` : ""}` : "";
    const evidence = (a.evidence || a.app_evidence || []);
    // 17.5: a missing area is practiced only once a difficulty is confirmed; the family's word wins
    const CONF = { seen_once: "נראה פעם אחת -- בודקים שוב", rechecking: "בבדיקה חוזרת", confirmed: "קושי אושר -- מתרגלים",
                   not_confirmed: "לא אושר (חד־פעמי)", fine: "" };
    const st = a.family_status || a.status;
    const confRow = NOT_PRACTICED.has(area) && (st && st !== "fine" || a.family_status) ? el("div", { class: "cg-actions" },
      el("span", { class: "muted", text: `${CONF[st] || st}${a.family_status ? " (נקבע ע\"י המשפחה)" : ""}` }),
      ...[["confirmed", "אישור"], ["not_confirmed", "ביטול"], ["", "החזרה להחלטת האפליקציה"]].map(([v, t]) => {
        const b = el("button", { class: "small", type: "button", text: t });
        b.addEventListener("click", async () => {
          b.disabled = true;
          try { await api(acct(`/needs/${area}/status`), { status: v }, "PUT"); await loadAccount(); } catch { b.disabled = false; }
        });
        return b;
      })) : null;
    const history = (a.history || []).slice(-12);
    const trend = history.length ? el("div", { class: "need-trend", "aria-label": "לאורך השיחות" },
      el("span", { class: "muted", text: "לאורך השיחות: " }),
      ...history.map((h) => el("span", { class: `dot lvl-${h.level}`, title: `${h.date}: ${NEED_LEVEL[h.level] || h.level}` })))
      : null;
    return el("div", { class: "need" },
      el("div", { class: "need-head" }, el("b", { text: name }),
        NOT_PRACTICED.has(area) ? el("span", { class: "muted", text: " · לא מתורגל באפליקציה עדיין" }) : null,
        who ? el("span", { class: "muted", text: ` · נקבע ע"י ${who}` }) : null),
      el("div", { class: "cg-actions" }, level, note, save),
      a.app_note ? p(`האפליקציה שמעה: ${a.app_note}`, "muted kv") : null,
      a.set_by === "app" && a.note ? p(a.note, "muted kv") : null,
      confRow,
      trend,
      evidence.length ? el("details", {}, el("summary", { class: "muted", text: "מה הוא אמר" }),
        el("ul", {}, evidence.map((q) => el("li", { dir: "auto", text: q })))) : null);
  }));
}
const POINT_STATUS = { new: "חדש", raised: "הועלה מול הקלינאית", dismissed: "לא רלוונטי" };
function renderTherapistPoints(points) {
  const list = (points || []).slice().reverse();
  if (!list.length) {
    $("therapist-points").replaceChildren(p("עדיין אין. נקודות יופיעו כשהאפליקציה תראה דפוס לאורך כמה שיחות.", "muted kv"));
    return;
  }
  $("therapist-points").replaceChildren(...list.map((pt) => {
    const mark = (status, label) => {
      const b = el("button", { class: `small${pt.status === status ? " on" : ""}`, type: "button", text: label });
      b.addEventListener("click", async () => {
        b.disabled = true;
        try { await api(acct(`/therapist-points/${encodeURIComponent(pt.id)}`), { status }, "PUT"); await loadAccount(); }
        catch { b.disabled = false; }
      });
      return b;
    };
    return el("div", { class: `need point-${pt.status}` },
      el("div", {}, el("b", { dir: "auto", text: pt.text })),
      p(`${pt.date} · ${POINT_STATUS[pt.status] || pt.status}${pt.why ? ` · ${pt.why}` : ""}`, "muted kv"),
      (pt.evidence || []).length ? el("details", {}, el("summary", { class: "muted", text: "מה הוא אמר" }),
        el("ul", {}, pt.evidence.map((q) => el("li", { dir: "auto", text: q })))) : null,
      el("div", { class: "cg-actions" }, mark("raised", "הועלה"), mark("dismissed", "לא רלוונטי"), mark("new", "חדש")));
  }));
}

// The app's adjustments (17): per area its level and time, the last decision, lock / undo; the log.
const ADJ_AREA = { naming: "שליפת שמות", connected_speech: "דיבור רציף (סיפור לשחזר)", summarizing: "סיכום במילים שלו",
                   sequencing: "סיפור לפי סדר", repetition: "חזרה אחריה", understanding: "הבנה", clarity: "בהירות הדיבור" };
const ADJ_RULE = { confirmed: "קושי אושר -- מתחילים לתרגל בהדרגה", mastered: "שולט -- רמה עולה", worse: "ירידה -- רמה יורדת, יותר זמן", stalled: "תקוע -- משנים גישה",
                   undo: "בוטל ע\"י המשפחה", lock: "ננעל", unlock: "שוחרר" };
const SHARE = { less: "פחות זמן", normal: "זמן רגיל", more: "יותר זמן" };
function renderAdjust(doc) {
  const areas = doc?.areas || {};
  const rows = Object.entries(ADJ_AREA).filter(([a]) => areas[a]).map(([a, name]) => {
    const st = areas[a];
    const lock = el("button", { class: `small${st.lock ? " on" : ""}`, type: "button", text: st.lock ? "נעול 🔒" : "נעילה" });
    lock.addEventListener("click", async () => {
      lock.disabled = true;
      try { await api(acct(`/progress/${a}/lock`), { lock: !st.lock }); await loadAccount(); } catch { lock.disabled = false; }
    });
    const undo = st.last ? el("button", { class: "small", type: "button", text: "ביטול השינוי האחרון" }) : null;
    undo?.addEventListener("click", async () => {
      undo.disabled = true;
      try { await api(acct(`/progress/${a}/undo`), {}); await loadAccount(); } catch { undo.disabled = false; }
    });
    return el("div", { class: "need" },
      el("div", { class: "need-head" }, el("b", { text: name }),
        el("span", { class: "muted", text: ` · רמה ${st.level}/5 · ${SHARE[st.share] || st.share}` +
                                           `${st.change_approach ? " · משנים גישה" : ""}` })),
      st.last ? p(`${st.last.date}: ${ADJ_RULE[st.last.rule] || st.last.rule} (${st.last.reason})`, "muted kv") : null,
      el("div", { class: "cg-actions" }, lock, undo));
  });
  const log = (doc?.log || []).slice(-12).reverse();
  $("adjust").replaceChildren(
    ...(rows.length ? rows : [p("עדיין אין מספיק תוצאות כדי להחליט (צריך 3 תוצאות לפחות בתחום).", "muted kv")]),
    log.length ? el("details", {}, el("summary", { class: "muted", text: "יומן השינויים" }),
      el("ul", {}, log.map((e) => el("li", { dir: "auto",
        text: `${e.date} · ${ADJ_AREA[e.area] || e.area} · ${ADJ_RULE[e.rule] || e.rule}${e.reason ? ` -- ${e.reason}` : ""}` })))) : null);
  const scores = doc?.therapist_scores || [];
  $("therapist-scores").replaceChildren(scores.length
    ? el("ul", {}, scores.map((t, i) => {
        const x = el("button", { class: "small x", type: "button", text: "✕" });
        x.addEventListener("click", async () => { await api(acct(`/therapist-scores/${i}`), null, "DELETE"); await loadAccount(); });
        return el("li", { dir: "auto" }, `${t.date} · ${t.test}: ${t.score}${t.note ? ` (${t.note})` : ""} `, x);
      }))
    : p("עדיין אין.", "muted kv"));
}
$("ts-add").addEventListener("click", async () => {
  const body = { date: $("ts-date").value, test: $("ts-test").value, score: $("ts-score").value, note: $("ts-note").value };
  if (!body.date || !body.test || !body.score) return;
  $("ts-add").disabled = true;
  try { await api(acct("/therapist-scores"), body); await loadAccount(); ["ts-test", "ts-score", "ts-note"].forEach((id) => { $(id).value = ""; }); }
  finally { $("ts-add").disabled = false; }
});

async function saveNeed(area, level, note, button) {
  if (area !== "goals" && !level) { $("needs-status").textContent = "צריך לבחור רמה."; return; }
  button.disabled = true;
  try {
    await api(acct(`/needs/${area}`), { level, note }, "PUT");
    await loadAccount();
    $("needs-status").textContent = `✓ נשמר (${NEED_AREA[area]}). בונה השיעורים יקבל את זה מהשיעור הבא.`;
  } catch {
    $("needs-status").textContent = "השמירה נכשלה.";
  } finally {
    button.disabled = false;
  }
}

function renderNotes(notes) {
  $("notes").value = notes?.text || "";
  $("notes-status").textContent = notes?.updated_at ? `נשמר ${when(notes.updated_at)}` : "";
  countNotes();
}
function countNotes() { $("notes-count").textContent = `${$("notes").value.length}/1500`; }
$("notes").addEventListener("input", () => { countNotes(); $("notes-status").textContent = "לא נשמר"; });
$("notes-save").addEventListener("click", async () => {
  $("notes-save").disabled = true;
  try {
    await api(acct("/notes"), { text: $("notes").value }, "PUT");
    await loadAccount();
    $("notes-status").textContent = "נשמר. ללחוץ \"לבנות מחדש\" בשיעור הבא כדי להחיל עכשיו.";
  } catch {
    $("notes-status").textContent = "השמירה נכשלה.";
  } finally {
    $("notes-save").disabled = false;
  }
});

// ---- progress graphs (09): plain SVG, drawn here, no libraries ----------------------------
const SVG = "http://www.w3.org/2000/svg";
const COLORS = { treated: "#3b7dd8", untreated: "#e8913a", own: "#38a169", hint: "#d4a72c", not_yet: "#d9534f" }; // read in light and dark (21)
function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  for (const c of children) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
}
const shortDate = (iso) => new Date(iso).toLocaleDateString("he-IL", { timeZone: "Asia/Jerusalem", day: "numeric", month: "numeric" });

// A line chart: x = sessions (oldest left), y = 0..yMax; series = [{key, color, values}]
function lineChart(points, series, { yMax = 100, yTicks = [0, 50, 100], yLabel = (v) => `${v}%`, height = 180 } = {}) {
  const W = 640, H = height, L = 40, R = 12, T = 10, B = 26;
  const x = (i) => L + (points.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (points.length - 1));
  const y = (v) => T + (H - T - B) * (1 - v / yMax);
  const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img" });
  for (const t of yTicks) {
    chart.append(svg("line", { x1: L, x2: W - R, y1: y(t), y2: y(t), style: "stroke: var(--line)" }),
                 svg("text", { x: L - 6, y: y(t) + 4, "text-anchor": "end" }, yLabel(t)));
  }
  const step = Math.max(1, Math.ceil(points.length / 8)); // at most ~8 date labels
  points.forEach((pt, i) => {
    if (i % step === 0 || i === points.length - 1) chart.append(svg("text", { x: x(i), y: H - 8, "text-anchor": "middle" }, shortDate(pt.date)));
  });
  for (const s of series) {
    const pts = points.map((pt, i) => [i, pt[s.key]]).filter(([, v]) => v !== null && v !== undefined);
    if (pts.length > 1) {
      chart.append(svg("polyline", { points: pts.map(([i, v]) => `${x(i)},${y(v)}`).join(" "), fill: "none",
                                     stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round" }));
    }
    for (const [i, v] of pts) {
      chart.append(svg("circle", { cx: x(i), cy: y(v), r: 4, fill: s.color },
        svg("title", {}, `${shortDate(points[i].date)}: ${yLabel(v)}`)));
    }
  }
  return chart;
}

function legend(items) {
  return el("div", { class: "legend" }, items.map(([color, text]) => el("span", {}, el("i", { style: `background:${color}` }), text)));
}

function renderProgress(data) {
  const box = $("progress");
  const withChecks = data.points.filter((pt) => pt.items);
  const withMood = data.points.filter((pt) => pt.mood);
  const out = [];
  if (withChecks.length) {
    const c = data.compare;
    const fmt = (v) => (v === null || v === undefined ? "–" : `${v}%`);
    out.push(el("h3", { text: "משחק השמות: כמה הוא שלף לבד, בלי רמז" }),
      legend([[COLORS.treated, "מילים ושמות שתורגלו"], [COLORS.untreated, "מילים חדשות (להשוואה)"]]),
      lineChart(withChecks, [{ key: "treated", color: COLORS.treated }, { key: "untreated", color: COLORS.untreated }]),
      c.before.sessions
        ? p(`ממוצע ${c.recent.sessions} השיחות האחרונות: תורגלו ${fmt(c.recent.treated)}, חדשות ${fmt(c.recent.untreated)} · ` +
            `${c.before.sessions} השיחות שלפני כן: תורגלו ${fmt(c.before.treated)}, חדשות ${fmt(c.before.untreated)}`, "kv")
        : null,
      p("בכל שיחה יש רק 3–5 פריטי בדיקה, ולכן כל נקודה קופצת. מה שחשוב הוא המגמה לאורך זמן. " +
        "אם \"תורגלו\" עולה יותר מ\"חדשות\", התרגול עצמו עוזר; אם שתיהן עולות, השליפה משתפרת בכלל.", "muted kv"));
  }
  const withSeq = data.points.filter((pt) => pt.sequencing !== null && pt.sequencing !== undefined);
  if (withSeq.length) {
    out.push(el("h3", { text: "סיפור לפי סדר: כמה מהסיפור הוא סיפר בסדר הנכון" }),
      lineChart(withSeq, [{ key: "sequencing", color: COLORS.treated }]),
      p("משימות כמו אצל הקלינאית: אירועים מעורבבים שהוא מסדר, או סיפור קצר שהוא מספר מחדש. " +
        "המשימה גדלה (עד 6 אירועים) כשהוא מצליח, וקטנה כשקשה לו.", "muted kv"));
  }
  const has = (k) => data.points.filter((pt) => pt[k] !== null && pt[k] !== undefined);
  const withStory = has("story");
  if (withStory.length) {
    out.push(el("h3", { text: "דיבור רציף: סיפור קצר שהוא מספר מחדש (מדידה קבועה)" }),
      lineChart(withStory, [{ key: "story", color: COLORS.treated }]),
      p("אותם סיפורים, באותה דרך, כל כמה שיחות -- כמו מדידה אצל קלינאית. כמה מהרעיונות העיקריים הוא העביר.", "muted kv"));
  }
  for (const [area, name] of [["repetition", "חזרה אחריה"], ["understanding", "הבנה"], ["clarity", "בהירות הדיבור"]]) {
    const pts = has(area);
    if (pts.length) {
      out.push(el("h3", { text: `${name}: משחק מדידה קבוע (%)` }), lineChart(pts, [{ key: area, color: COLORS.untreated }]));
    }
  }
  const withTalk = has("avg_words");
  if (withTalk.length) {
    out.push(el("h3", { text: "שיחה חופשית: אורך התשובות שלו (מילים בממוצע)" }),
      lineChart(withTalk, [{ key: "avg_words", color: COLORS.own }],
                { yMax: 30, yTicks: [0, 10, 20, 30], yLabel: (v) => `${v}` }),
      p("נמדד בנפרד מהתרגול: האם השיפור מגיע לשיחה עצמה.", "muted kv"));
  }
  const withView = has("his_view");
  if (withView.length) {
    out.push(el("h3", { text: "איך הוא מרגיש שהדיבור הולך (1-5, מהמילים שלו)" }),
      lineChart(withView, [{ key: "his_view", color: COLORS.hint }], { yMax: 5, yTicks: [1, 3, 5], yLabel: (v) => `${v}` }));
  }
  const withSumm = data.points.filter((pt) => pt.summarizing !== null && pt.summarizing !== undefined);
  if (withSumm.length) {
    out.push(el("h3", { text: "סיכום במילים שלו: כמה מהרעיונות העיקריים הוא העביר" }),
      lineChart(withSumm, [{ key: "summarizing", color: COLORS.own }]),
      p("היא מקריאה פסקה קצרה והוא מספר אותה במילים שלו. הפסקה גדלה (עד 6 רעיונות) כשהוא מצליח, וקטנה כשקשה לו.", "muted kv"));
  }
  const withOwn = data.points.filter((pt) => pt.self_found || pt.not_found);
  if (withOwn.length) {
    const top = Math.max(2, ...withOwn.map((pt) => Math.max(pt.self_found, pt.not_found)));
    out.push(el("h3", { text: "שמות בשיחה החופשית: מצא לבד / לא מצא" }),
      legend([[COLORS.own, "מצא לבד (אחרי מאמץ)"], [COLORS.not_yet, "לא מצא"]]),
      lineChart(withOwn, [{ key: "self_found", color: COLORS.own }, { key: "not_found", color: COLORS.not_yet }],
                { yMax: top, yTicks: [0, Math.round(top / 2), top], yLabel: (v) => String(v), height: 140 }),
      p("שמות שהוא חיפש בעצמו באמצע השיחה, בלי שהמטפלת שאלה. זה הסימן הקרוב ביותר לשליפה בחיים האמיתיים.", "muted kv"));
  }
  if (withMood.length) {
    out.push(el("h3", { text: "מצב רוח" }),
      lineChart(withMood, [{ key: "mood", color: COLORS.own }],
                { yMax: 3, yTicks: [1, 2, 3], yLabel: (v) => ({ 1: "ירוד", 2: "בסדר", 3: "טוב" }[v] || ""), height: 130 }));
  }
  const w = data.words;
  if (w.total) {
    const pct = (n) => `${(100 * n) / w.total}%`;
    out.push(el("h3", { text: `בנק המילים: ${w.total} מילים ושמות` }),
      el("div", { class: "wordbar", role: "img", "aria-label": `${w.own} לבד, ${w.hint} עם רמז, ${w.not_yet} עוד לא` },
        el("span", { style: `width:${pct(w.own)};background:${COLORS.own}` }),
        el("span", { style: `width:${pct(w.hint)};background:${COLORS.hint}` }),
        el("span", { style: `width:${pct(w.not_yet)};background:${COLORS.not_yet}` })),
      legend([[COLORS.own, `לבד בפעם האחרונה: ${w.own}`], [COLORS.hint, `עם רמז: ${w.hint}`], [COLORS.not_yet, `עוד לא: ${w.not_yet}`]]));
  }
  box.replaceChildren(...(out.length ? out : [p("עדיין אין מספיק נתונים לגרפים. הם יופיעו אחרי השיחות הראשונות.", "muted")]));
}

// ---- export for the therapist (09): a print view built from the data already loaded ------
function probeStats(results) {
  const by = (kind) => (results || []).filter((r) => r.kind === kind);
  const ownShare = (rs) => rs.length ? `${Math.round(100 * rs.filter((r) => r.result === "uncued").length / rs.length)}%` : "–";
  const count = (res) => (results || []).filter((r) => r.result === res).length;
  return { uncued: count("uncued"), cued: count("cued"), failed: count("failed"),
           treated: ownShare(by("treated")), untreated: ownShare(by("untreated")) };
}

// t(): maps each English text to its Hebrew translation (identity when not translating).
function buildExport(n, t = (s) => s, translated = false) {
  const ov = lastOverview;
  const sessions = lastSessions.filter((s) => s.status !== "active" && (!s.excluded || $("progress-left-out").checked))
    .slice(0, n); // left out (20.5): only when shown
  const oldest = sessions.at(-1)?.started_at;
  const newest = sessions[0]?.started_at;
  const list = (items) => el("ul", {}, items.map((i) => el("li", { dir: "auto", text: t(i) })));
  const out = [
    el("h1", { text: "דברו איתי · סיכום לקלינאית" }),
    p(`${ov.email} · ${sessions.length} שיחות${oldest ? ` · ${when(oldest, false)} – ${when(newest, false)}` : ""} · הופק ${when(new Date().toISOString(), false)}`, "meta"),
    p(translated
      ? "הסיכומים תורגמו לעברית אוטומטית מהסיכומים שהמערכת כותבת באנגלית. הבדיקות: ✓ שלף לבד · ~ עם רמז · ✗ לא שלף."
      : "סיכומי השיחות נכתבים על ידי המערכת באנגלית; המילים והשמות שלו מופיעים בעברית. הבדיקות: ✓ שלף לבד · ~ עם רמז · ✗ לא שלף.", "meta"),
    el("h2", { text: "מטרות ודגשים" }),
    ov.next_plan?.rendered ? p(`השיעור הבא: ${t((ov.next_plan.rendered.split("\n")[1] || "").replace(/^Main goal \([a-z_]+\): /, ""))}`) : null,
    ov.notes?.text ? el("div", {}, el("h3", { text: "הערות המשפחה / הקלינאית" }), el("p", { dir: "auto", text: t(ov.notes.text) })) : null,
    ov.memory?.focus_next_session?.length ? el("div", {}, el("h3", { text: "דגשים לשיחה הבאה" }), list(ov.memory.focus_next_session)) : null,
  ];

  const withProbes = sessions.filter((s) => s.probe_results?.length);
  if (withProbes.length) {
    out.push(el("h2", { text: "משחק השמות לאורך זמן (שליפה בלי רמז)" }), el("table", {},
      el("thead", {}, el("tr", {}, ["תאריך", "✓", "~", "✗", "✓ במילים שתורגלו", "✓ במילים חדשות"].map((h) => el("th", { text: h })))),
      el("tbody", {}, withProbes.slice().reverse().map((s) => {
        const st = probeStats(s.probe_results);
        return el("tr", {}, [when(s.started_at, false), st.uncued, st.cued, st.failed, st.treated, st.untreated]
          .map((v) => el("td", { text: String(v) })));
      }))));
  }

  out.push(el("h2", { text: "השיחות" }));
  for (const s of sessions) {
    const st = probeStats(s.probe_results);
    out.push(el("div", { class: "ex-session" },
      el("h3", { text: [when(s.started_at), minutes(s.started_at, s.ended_at), MOOD[s.mood], GOAL[s.plan_goal]].filter(Boolean).join(" · ") }),
      s.summary ? el("p", { dir: "auto", text: t(s.summary) }) : p("(אין סיכום)", "meta"),
      s.highlights?.length ? el("p", { dir: "auto", text: `הצלחות: ${s.highlights.map(t).join(" · ")}` }) : null,
      s.difficulties?.length ? el("p", { dir: "auto", text: `קשיים: ${s.difficulties.map(t).join(" · ")}` }) : null,
      s.probe_results?.length
        ? el("p", { dir: "auto", text: `משחק השמות: ${s.probe_results.map((r) => `${RESULT[r.result] || "?"} ${r.word}`).join("  ")}  (✓${st.uncued} ~${st.cued} ✗${st.failed})` })
        : null,
      ownNamesLine(s),
      sequencingLine(s),
    ));
  }

  const sections = ov.memory?.sections || {};
  const obs = [["language_observations", "תצפיות על הדיבור"], ["what_works", "מה עובד"], ["what_to_avoid", "ממה להימנע"]]
    .filter(([k]) => sections[k]?.length);
  if (obs.length) {
    out.push(el("h2", { text: "תצפיות" }), ...obs.map(([k, title]) => el("div", {}, el("h3", { text: title }), list(sections[k]))));
  }

  const seqs = sessions.filter((s) => s.sequencing?.status === "done");
  if (seqs.length) {
    out.push(el("h2", { text: "סיפור לפי סדר" }), el("table", {},
      el("thead", {}, el("tr", {}, ["תאריך", "משימה", "אירועים", "בסדר הנכון", "עזרה"].map((h) => el("th", { text: h })))),
      el("tbody", {}, seqs.slice().reverse().map((s) => el("tr", {},
        [when(s.started_at, false), `${SEQ_TASK[s.sequencing.task] || s.sequencing.task} · ${s.sequencing.title || ""}`,
         `${s.sequencing.events_included}/${s.sequencing.events}`, `${s.sequencing.order_pct}%`,
         s.sequencing.needed_help ? "כן" : "לא"].map((v) => el("td", { dir: "auto", text: String(v) })))))));
  }

  const own = sessions.flatMap((s) => s.own_names || []);
  if (own.length) {
    const names = (r) => [...new Set(own.filter((o) => o.result === r).map((o) => o.word))].join(", ");
    out.push(el("h2", { text: "שמות בשיחה החופשית" }),
      p("שמות שהוא חיפש בעצמו באמצע השיחה (הפסקה, תיאור במקום שם, תיקון עצמי), בלי שהמטפלת שאלה.", "meta"),
      names("self_found") ? el("p", { dir: "auto", text: `★ מצא לבד: ${names("self_found")}` }) : null,
      names("not_found") ? el("p", { dir: "auto", text: `… לא מצא: ${names("not_found")}` }) : null);
  }

  const hard = (ov.word_bank || []).filter((w) => (w.failed || 0) + (w.cued || 0) > 0)
    .sort((a, b) => ((b.failed || 0) * 2 + (b.cued || 0)) - ((a.failed || 0) * 2 + (a.cued || 0))).slice(0, 15);
  if (hard.length) {
    out.push(el("h2", { text: "המילים הקשות" }), el("table", {},
      el("thead", {}, el("tr", {}, ["מילה", "ניסיונות", "✓", "~", "✗", "תוצאה אחרונה"].map((h) => el("th", { text: h })))),
      el("tbody", {}, hard.map((w) => el("tr", {},
        [w.word, w.attempts ?? 0, w.uncued ?? 0, w.cued ?? 0, w.failed ?? 0, RESULT_TEXT[w.last_result] || ""]
          .map((v) => el("td", { dir: "auto", text: String(v) })))))));
  }
  out.push(el("p", { class: "ex-footer", dir: "ltr", text: "דברו איתי · Made by Tomer Shimshi" }));
  $("export").replaceChildren(...out.filter(Boolean));
}

function printExport() {
  document.body.classList.add("printing");
  window.print();
}

// Ask first (an inline window -- no browser dialogs): translate to Hebrew, or print as is?
$("export-run").addEventListener("click", () => {
  if (!lastOverview) return;
  $("export-status").textContent = "";
  $("translate-ask").hidden = false;
});
$("translate-no").addEventListener("click", () => {
  $("translate-ask").hidden = true;
  buildExport(Number($("export-n").value));
  printExport();
});
$("translate-yes").addEventListener("click", async () => {
  $("translate-ask").hidden = true;
  const n = Number($("export-n").value);
  const texts = new Set(); // every English text the export shows, collected by a dry build
  buildExport(n, (s) => { if (s && /[A-Za-z]{3}/.test(s)) texts.add(s); return s; });
  const originals = [...texts];
  busy($("export-status"), "מתרגם לעברית, זה עשוי לקחת עד כדקה");
  $("export-run").disabled = true;
  try {
    const { translations } = await api(acct("/export/translate"), { texts: originals });
    const map = new Map(originals.map((o, i) => [o, translations[i]]));
    buildExport(n, (s) => map.get(s) ?? s, true);
    $("export-status").textContent = "";
  } catch {
    buildExport(n);
    $("export-status").textContent = "התרגום לא הצליח, הסיכום יודפס באנגלית.";
  } finally {
    $("export-run").disabled = false;
  }
  printExport();
});
window.addEventListener("afterprint", () => document.body.classList.remove("printing"));

// ---- the face-lift (21): summary tiles and tabs ----------------------------------------------
const TABS = {
  overview: ["flags", "sec-progress", "sec-sessions"],
  lesson: ["sec-plan", "sec-names-game", "sec-next-prompt", "sec-notes"],
  knows: ["sec-memory", "sec-profile", "sec-needs", "sec-words", "sec-adjust"],
  tools: ["sec-voice", "sec-export", "sec-info", "sec-research", "sec-games", "sec-reset"],
};
function showTab(name) {
  if (!TABS[name]) name = "overview";
  for (const [tab, ids] of Object.entries(TABS)) {
    ids.forEach((id, i) => { const node = $(id); if (node) { node.hidden = tab !== name; node.style.order = i; } });
  }
  document.querySelectorAll(".cg-tabs [data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  try { localStorage.setItem("cg-tab", name); } catch { /* private window: not remembered */ }
  if (location.hash.slice(1) !== name) history.replaceState(null, "", `#${name}`);
}
document.querySelectorAll(".cg-tabs [data-tab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
// A click outside an open "⋯" menu closes it.
document.addEventListener("click", (e) => {
  document.querySelectorAll(".more-menu[open]").forEach((m) => { if (!m.contains(e.target)) m.open = false; });
});
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));
showTab(location.hash.slice(1) || (() => { try { return localStorage.getItem("cg-tab"); } catch { return null; } })() || "overview");

function tile(key, value, sub, { cls = "", tab = null, extra = null } = {}) {
  const node = el(tab ? "button" : "div", { class: `tile ${cls}`, type: tab ? "button" : null },
    el("span", { class: "k", text: key }), el("span", { class: "v", text: value }),
    sub ? el("span", { class: "s", text: sub }) : null, extra);
  if (tab) node.addEventListener("click", () => showTab(tab));
  return node;
}
// A small trend line for the names game (points: 0-100, oldest first).
function sparkline(values) {
  if (values.length < 2) return null;
  const W = 120, H = 30, x = (i) => (i * W) / (values.length - 1), y = (v) => H - 3 - (v / 100) * (H - 6);
  const line = svg("polyline", { points: values.map((v, i) => `${x(i)},${y(v)}`).join(" "), fill: "none",
                                 stroke: "currentColor", "stroke-width": 2.5 });
  const dot = svg("circle", { cx: x(values.length - 1), cy: y(values.at(-1)), r: 3, fill: "currentColor" });
  const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", "aria-hidden": "true",
                             style: "color: var(--accent)" });
  chart.append(line, dot);
  return chart;
}
function renderGlance(ov, sessions, progress) {
  const last = sessions.find((s) => s.status === "ended");
  const open = (ov.flags || []).filter((f) => f.status === "open").length;
  const since = Date.now() - 14 * 86400000;
  const names = (progress.points || []).filter((pt) => pt.items && new Date(pt.date) >= since)
    .map((pt) => [pt.treated, pt.untreated].filter((v) => v !== null && v !== undefined))
    .filter((v) => v.length).map((v) => Math.round(v.reduce((a, b) => a + b, 0) / v.length));
  const planFailed = last?.plan_status === "failed";
  $("glance").replaceChildren(
    tile("שיחה אחרונה", last ? when(last.started_at, false) : "אין עדיין",
         last ? [minutes(last.started_at, last.ended_at), MOOD[last.mood]].filter(Boolean).join(" · ") : "", { tab: "overview" }),
    tile("דורש תשומת לב", String(open), open ? (open === 1 ? "התראה אחת פתוחה" : "התראות פתוחות") : "הכול בסדר",
         { cls: open ? "alert" : "", tab: "overview" }),
    tile("משחק השמות, שבועיים", names.length ? `${Math.round(names.reduce((a, b) => a + b, 0) / names.length)}%` : "–",
         names.length ? "בלי רמז, בממוצע" : "עוד אין משחקים", { tab: "overview", extra: sparkline(names) }),
    tile("השיעור הבא", planFailed ? "נכשל" : ov.next_plan?.built_at ? "מוכן" : "אין",
         ov.next_plan?.built_at ? `נבנה ${when(ov.next_plan.built_at)}` : "", { cls: planFailed ? "bad" : "", tab: "lesson" }),
  );
}

// ---- loading ----------------------------------------------------------------------------
// Left-out conversations (20.5) are in the graphs only when asked; the therapist export uses what's shown.
const progressPath = () => ($("progress-left-out").checked ? "/progress?left_out=1" : "/progress");
$("progress-left-out").addEventListener("change", async () => {
  try { renderProgress(await api(acct(progressPath()))); } catch { status("טעינת ההתקדמות נכשלה."); }
});

async function loadAccount() {
  status("טוען…");
  try {
    const [ov, ss, pr] = await Promise.all([api(acct("/overview")), api(acct("/sessions")), api(acct(progressPath()))]);
    renderProgress(pr);
    renderGlance(ov, ss.sessions, pr);
    lastOverview = ov;
    lastSessions = ss.sessions;
    renderFlags(ov.flags);
    renderSessions(ss.sessions);
    renderPlan(ov.next_plan, ov.notes);
    renderMemory(ov.memory, ov.profile);
    renderWords(ov.word_bank);
    renderNamesGame(ov.check_in_set, ov.check_in_history);
    renderResearch(ov.research_notes);
    renderGames(ov.recommendations, ov.games_profile);
    renderProfile(ov.profile);
    renderNeeds(ov.needs);
    renderTherapistPoints(ov.needs?.therapist_points);
    renderAdjust(ov.progress);
    renderNotes(ov.notes);
    const au = ov.audio || {};
    audioUsage = au.enabled && au.files !== null && au.files !== undefined
      ? `${au.files} קבצים, ${(au.bytes / 1048576).toFixed(1)}MB` : "";
    renderVoice(ov.settings);
    fillReminderForm(ov.reminder);
    $("voice-summary").append(reminderSummary(ov.reminder) || "");
    $("history").replaceChildren(p("נטען בפתיחה…", "muted"));
    if ($("sec-history").open) loadHistory();
    $("next-prompt").replaceChildren(p("נטען בפתיחה…", "muted"));
    if ($("sec-next-prompt").open) loadNextPrompt();
    const a = accounts.find((x) => x.email === account);
    $("account-summary").textContent = a ? `${a.sessions} שיחות · ${a.words} מילים` : "";
    $("content").hidden = false;
    status("");
  } catch (err) {
    status(err.status === 403 ? "לחשבון הזה אין הרשאת מטפל." : "הטעינה נכשלה. נסה לרענן.");
  }
}

function renderBilling(b) {
  const box = $("billing");
  box.hidden = !b?.paused;
  if (!b?.paused) return;
  const spend = b.cost != null ? `${Math.round(b.cost)} מתוך ${Math.round(b.budget)} ${b.currency === "ILS" ? "₪" : b.currency || ""}` : "";
  box.replaceChildren(
    el("div", { class: "title", text: "⏸️ השימוש במודלים מושהה (עצירה רכה של ההוצאות)" }),
    p(`ההוצאה החודשית הגיעה ל־75% מהתקציב${spend ? ` (${spend})` : ""}${b.since ? `, מאז ${when(b.since)}` : ""}. ` +
      "שיחות חדשות, עדכוני זיכרון ובניית שיעורים ממתינים. האתר והנתונים זמינים כרגיל, ושום דבר לא אבד: " +
      "שיחות שהסתיימו יעובדו אחרי ההמשך. בתחילת חודש חדש זה מתאפס לבד. בכל מקרה, ב־100% מתג הניתוק עוצר הכל."),
    confirmButton("▶️ להמשיך (לשאר החודש)", "להמשיך את השימוש במודלים? ההוצאה תמשיך לגדול.", async (where) => {
      busy(where, "ממשיך");
      try {
        await api("api/caregiver/billing/resume", {});
        await loadAccounts();
        status("✓ השימוש במודלים חודש. שיחות שהמתינו יעובדו בסבב הבא (או בכפתור העיבוד).");
      } catch {
        where.textContent = "ההמשך נכשל. נסה שוב.";
      }
    }),
  );
}

async function loadAccounts() {
  const data = await api("api/caregiver/accounts");
  accounts = data.accounts;
  renderBilling(data.billing);
  let saved = "";
  try { saved = localStorage.getItem(ACCOUNT_KEY) || ""; } catch { /* storage may be blocked */ }
  const emails = accounts.map((a) => a.email);
  // Default: the last one viewed, else the caregiver's own account (to validate with own sessions).
  account = emails.includes(saved) ? saved : emails.includes(data.me) ? data.me : emails[0] || "";
  $("account").replaceChildren(...accounts.map((a) => new Option(a.email, a.email, false, a.email === account)));
  $("account-bar").hidden = false;
}

$("account").addEventListener("change", () => {
  account = $("account").value;
  try { localStorage.setItem(ACCOUNT_KEY, account); } catch { /* ignore */ }
  $("reset-confirm").value = "";
  validateReset();
  $("reset-status").textContent = "";
  $("rebuild-status").textContent = "";
  $("voice-form").hidden = true;
  $("memory-status").textContent = "";
  $("words-status").textContent = "";
  loadAccount();
});
$("sec-history").addEventListener("toggle", () => { if ($("sec-history").open) loadHistory(); });

async function loadNextPrompt() {
  busy($("next-prompt"), "בונה את הפרומפט");
  try {
    const data = await api(acct("/next-prompt"));
    $("next-prompt").replaceChildren(
      p(`גרסת הנחיות ${data.prompt_version} · ${data.text.length.toLocaleString("he-IL")} תווים`, "muted kv"),
      el("pre", { class: "plan prompt", dir: "auto", text: data.text }));
  } catch {
    $("next-prompt").replaceChildren(p("טעינת הפרומפט נכשלה.", "muted"));
  }
}
$("sec-next-prompt").addEventListener("toggle", () => { if ($("sec-next-prompt").open) loadNextPrompt(); });

// ---- rebuild the next lesson now (with the deployed code and prompts) ---------------------
$("rebuild").addEventListener("click", async () => {
  const forAccount = account;
  $("rebuild").disabled = true;
  busy($("rebuild-status"), "בונה את השיעור הבא, זה עשוי לקחת עד דקה-שתיים");
  try {
    const body = await api(acct("/plan/rebuild"), {});
    if (forAccount !== account) return; // switched accounts meanwhile: the page shows the other one
    await loadAccount();
    $("rebuild-status").textContent = body.plan_status === "done"
      ? `השיעור הבא נבנה מחדש (${when(new Date().toISOString())}).`
      : `הבנייה נכשלה, השיעור הקודם נשאר: ${body.error || ""}`;
  } catch (err) {
    $("rebuild-status").textContent = err.status === 409
      ? "אין עדיין זיכרון בחשבון הזה: השיחה הבאה תהיה פגישת היכרות."
      : "הבנייה נכשלה. נסה שוב בעוד רגע.";
  } finally {
    $("rebuild").disabled = false;
  }
});

// ---- reset (from 4.5) ------------------------------------------------------------------
function validateReset() {
  $("reset-run").disabled = $("reset-confirm").value.trim().toLowerCase() !== account;
}
$("reset-confirm").addEventListener("input", validateReset);
$("reset-run").addEventListener("click", async () => {
  const scope = document.querySelector('input[name="reset-scope"]:checked').value;
  $("reset-run").disabled = true;
  busy($("reset-status"), "מבצע");
  try {
    const body = await api(acct("/reset"), { scope, confirm_email: $("reset-confirm").value });
    $("reset-confirm").value = "";
    await loadAccounts();
    await loadAccount();
    $("reset-status").textContent = (scope === "memory"
      ? "הזיכרון נמחק. השיחה הבאה תתחיל כמו פגישה ראשונה."
      : `נמחקו ${body.deleted_sessions} שיחות וכל הזיכרון.`) + (body.backup ? " (נשמר גיבוי)" : "");
  } catch {
    $("reset-status").textContent = "הפעולה נכשלה. נסה שוב.";
    validateReset();
  }
});

// ---- sign-in -----------------------------------------------------------------------------
async function onUserChanged(user) {
  $("signout").hidden = !user;
  $("signin-box").hidden = !!user;
  if (!user) {
    $("content").hidden = true;
    $("account-bar").hidden = true;
    status("");
    return;
  }
  try {
    await loadAccounts();
    await loadAccount();
  } catch (err) {
    $("content").hidden = true;
    status(err.status === 403 ? `החשבון ${user.email} אינו חשבון מטפל.` : "לא הצלחנו להתחבר לשרת. נסה שוב בעוד רגע.");
  }
}

$("signin").addEventListener("click", () => signIn().catch(() => status("ההתחברות לא הצליחה. נסה שוב.")));
$("signout").addEventListener("click", () => signOut());

try {
  await initAuth(onUserChanged);
} catch {
  status("ההתחברות עדיין לא מוגדרת בשרת.");
}
