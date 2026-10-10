// Caregiver page (08): one view per allowlisted account. All data comes from /api/caregiver/*,
// which only answers caregivers. Everything from the server is shown as TEXT (textContent),
// never as HTML: transcripts and memories contain whatever was said.
const ASSET_QUERY = new URL(import.meta.url).search;
const { initAuth, signIn, signOut, idToken } = await import(`./auth.js${ASSET_QUERY}`);

const $ = (id) => document.getElementById(id);
const ACCOUNT_KEY = "caregiver.account";

const MOOD = { good: "מצב רוח טוב", ok: "מצב רוח בסדר", low: "מצב רוח ירוד", unknown: "" };
const RESULT = { uncued: "✓", cued: "~", failed: "✗" };
const RESULT_TEXT = { uncued: "לבד", cued: "עם רמז", failed: "לא הצליח" };
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
                cut_off: "קטעה אותו", other: "אחר" };

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
    const unprocessed = (s.status === "active" && s.started_at && Date.now() - new Date(s.started_at) > 20 * 60000)
      || (s.status === "ended" && ["pending", "failed", "processing"].includes(s.memory_status))
      || (s.memory_status === "done" && ["pending", "failed"].includes(s.plan_status));
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
    const problems = [s.memory_status === "failed" && "עדכון הזיכרון נכשל", s.plan_status === "failed" && "בניית השיעור נכשלה"]
      .filter(Boolean);
    return el("div", { class: "session" },
      el("div", { class: "head" },
        el("span", { class: "when", text: when(s.started_at) }),
        el("span", { class: "muted", text: [minutes(s.started_at, s.ended_at), `${s.turn_count || 0} תורות`,
                                            END_REASON[s.end_reason] || s.end_reason || (s.status === "active" ? "פעילה" : "")]
                                            .filter(Boolean).join(" · ") }),
        s.plan_goal ? el("span", { class: "chip", text: GOAL[s.plan_goal] || s.plan_goal }) : null,
        s.plan_type === "intro" ? el("span", { class: "chip", text: "היכרות" }) : null,
        MOOD[s.mood] ? el("span", { class: "chip", text: MOOD[s.mood] }) : null,
        modelChip("memory", s.memory_model), modelChip("plan", s.plan_model),
        ...problems.map((t) => el("span", { class: "chip warn", text: t })),
      ),
      s.summary ? p(s.summary) : p(s.memory_status === "done" ? "" : "עדיין אין סיכום לשיחה הזו.", "muted"),
      s.highlights?.length ? p(`הצלחות: ${s.highlights.join(" · ")}`) : null,
      s.difficulties?.length ? p(`קשיים: ${s.difficulties.join(" · ")}`) : null,
      probeChips(s.probe_results),
      voiceLine(s),
      el("div", { class: "cg-actions" }, button, promptButton, recordingButton(s), processButton),
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
    if (!items.length) return null;
    return el("div", {}, el("h3", { text: title }), el("ul", {}, items.map((item) => el("li", {},
      el("span", { class: "mem-item" }, el("span", { dir: "auto", text: item }),
        editable ? confirmButton("✕", "להסיר את הפריט (גם מהסיכום)?", (wrap) => removeItem(key, item, wrap), "x") : null)))));
  });
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

function renderMemory(memory) {
  if (!memory.memory_prompt) {
    $("memory").replaceChildren(p("אין זיכרון בחשבון הזה (השיחה הבאה תהיה פגישת היכרות).", "muted"));
    return;
  }
  $("memory").replaceChildren(
    p(`מבוסס על ${memory.sessions_processed || 0} שיחות · עודכן ${when(memory.updated_at)}`, "muted kv"),
    el("h3", { text: "מה המטפלת מקבלת בתחילת כל שיחה" }),
    el("pre", { class: "plan", dir: "auto", text: memory.memory_prompt }),
    memory.focus_next_session?.length
      ? el("div", {}, el("h3", { text: "דגשים לשיחה הבאה" }),
           el("ul", {}, memory.focus_next_session.map((f) => el("li", { dir: "auto", text: f }))))
      : null,
    ...sectionLists(memory.sections, true),
  );
}

function versionKind(version) {
  if (version?.startsWith("edit-")) return " · לפני הסרה (פריט או מילה)";
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
  const head = ["מילה", "ניסיונות", "✓ לבד", "~ עם רמז", "✗", "תוצאה אחרונה", "הופיעה לאחרונה", "לתרגול שוב", ""];
  $("words").replaceChildren(el("div", { class: "table-wrap" }, el("table", { class: "words" },
    el("thead", {}, el("tr", {}, head.map((h) => el("th", { text: h })))),
    el("tbody", {}, rows.map((r) => el("tr", {},
      el("td", { dir: "auto", text: r.word }), el("td", { text: r.attempts ?? 0 }), el("td", { text: r.uncued ?? 0 }),
      el("td", { text: r.cued ?? 0 }), el("td", { text: r.failed ?? 0 }),
      el("td", { text: `${RESULT[r.last_result] || ""} ${RESULT_TEXT[r.last_result] || ""}${r.last_cue_level ? ` (${r.last_cue_level})` : ""}` }),
      el("td", { text: r.last_seen || "" }), el("td", { text: r.next_due || "" }),
      el("td", {}, confirmButton("✕", `להסיר את "${r.word}"?`, (where) => removeWord(r.word, where), "x")),
    ))),
  )));
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
const COLORS = { treated: "#2f6fdf", untreated: "#e08a1e", own: "#38a169", hint: "#ecc94b", not_yet: "#e53e3e" };
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
    chart.append(svg("line", { x1: L, x2: W - R, y1: y(t), y2: y(t), stroke: "#e3e7f0" }),
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
    out.push(el("h3", { text: "בדיקת השליפה: כמה הוא שלף לבד, בלי רמז" }),
      legend([[COLORS.treated, "מילים ושמות שתורגלו"], [COLORS.untreated, "מילים חדשות (להשוואה)"]]),
      lineChart(withChecks, [{ key: "treated", color: COLORS.treated }, { key: "untreated", color: COLORS.untreated }]),
      c.before.sessions
        ? p(`ממוצע ${c.recent.sessions} השיחות האחרונות: תורגלו ${fmt(c.recent.treated)}, חדשות ${fmt(c.recent.untreated)} · ` +
            `${c.before.sessions} השיחות שלפני כן: תורגלו ${fmt(c.before.treated)}, חדשות ${fmt(c.before.untreated)}`, "kv")
        : null,
      p("בכל שיחה יש רק 3–5 פריטי בדיקה, ולכן כל נקודה קופצת. מה שחשוב הוא המגמה לאורך זמן. " +
        "אם \"תורגלו\" עולה יותר מ\"חדשות\", התרגול עצמו עוזר; אם שתיהן עולות, השליפה משתפרת בכלל.", "muted kv"));
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
  const sessions = lastSessions.filter((s) => s.status !== "active").slice(0, n);
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
    out.push(el("h2", { text: "בדיקת שליפה לאורך זמן" }), el("table", {},
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
        ? el("p", { dir: "auto", text: `בדיקה: ${s.probe_results.map((r) => `${RESULT[r.result] || "?"} ${r.word}`).join("  ")}  (✓${st.uncued} ~${st.cued} ✗${st.failed})` })
        : null,
    ));
  }

  const sections = ov.memory?.sections || {};
  const obs = [["language_observations", "תצפיות על הדיבור"], ["what_works", "מה עובד"], ["what_to_avoid", "ממה להימנע"]]
    .filter(([k]) => sections[k]?.length);
  if (obs.length) {
    out.push(el("h2", { text: "תצפיות" }), ...obs.map(([k, title]) => el("div", {}, el("h3", { text: title }), list(sections[k]))));
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

// ---- loading ----------------------------------------------------------------------------
async function loadAccount() {
  status("טוען…");
  try {
    const [ov, ss, pr] = await Promise.all([api(acct("/overview")), api(acct("/sessions")), api(acct("/progress"))]);
    renderProgress(pr);
    lastOverview = ov;
    lastSessions = ss.sessions;
    renderFlags(ov.flags);
    renderSessions(ss.sessions);
    renderPlan(ov.next_plan, ov.notes);
    renderMemory(ov.memory);
    renderWords(ov.word_bank);
    renderResearch(ov.research_notes);
    renderGames(ov.recommendations, ov.games_profile);
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
