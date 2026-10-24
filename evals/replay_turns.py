"""Replays the flagged turns of REAL sessions on Gemini Live: the exact conversation up to the moment
she went wrong (no reaction at a step change, a double question, a question he had already answered),
then her turn again -- with today's prompt and with a variant -- and the judge says if it's fixed.

For each flagged point (found by evals/session_metrics.py on the account's sessions):
  - the prompt: the one that session's tutor got (its archived copy), its fixed sections brought up
    to today's tutor prompt (prompts/tutor.yaml) -- so "current" is what runs today -- then the
    variant's changes;
  - the history: the session's start note, every turn of theirs, and each step change as the
    next_step call and the page's reply, up to his answer just before her flagged turn;
  - his answer is sent as text and she answers live; the page's rules are simulated (the question
    guard, the min answers per step, the reply with the next step).

    python -m evals.replay_turns --account <email> --sessions 10 --variants current --runs 2 --out <dir>

Credit: one short Live session per point, variant and run (~$0.05 each). `--issues`, `--only` and
`--limit` keep it small; the judge is batched and cached. Replays run --parallel at a time (default 5)
and each is saved as it finishes (<out>/replays.jsonl): a stopped run continues where it left off with
the same command, and a changed prompt or tool replays its points again (the key holds them). Runs are saved to --out (outside the repo); the
terminal shows the results. Text stands in for his voice: see evals/README.md.
"""

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

from google import genai
from google.genai import types

from app.config import get_settings
from app.live_token import END_SESSION_TOOL, NEXT_STEP_TOOL
from app.prompts import render_tutor_prompt
from app.steps import overview
from app.store import FirestoreSessionStore
from evals.judge import judge_many
from evals.session_metrics import REPEAT_OVERLAP, _questions, _words, load_sessions, measure, session_turns

START_NOTE = "[The patient just opened the app. Greet him and begin the session. CURRENT STEP: {step}]"
HOLD_QUESTION = ("Noted. You just asked him a question: stop talking now and wait for his answer. After his answer, "
                 "call next_step again.")
HOLD_ANSWERS = ("Not yet -- stay on this topic. Now: react to what he just said and ask ONE follow-up question about "
                "his own words. After his answer, call next_step again.")
# The prompt's fixed sections (no per-session content): replaced by today's versions.
FIXED = ("LANGUAGE", "ROLE", "HOW THE SESSION WORKS", "HOW YOU TALK", "OPENING, TIMING AND CLOSING",
         "FATIGUE AND FRUSTRATION", "SAFETY")


# --- the variants: what a fix changes (the prompt, the tool, the page's reply) ---------------------------

def reply_current(step_text: str, args: dict) -> tuple[str, str]:
    return "advanced", f"CURRENT STEP: {step_text}"


REACTION_TOOL = types.FunctionDeclaration(
    name="next_step",
    description=(
        "Call when his answer has just finished the CURRENT STEP -- FIRST, before you say anything, with your "
        "reaction to his answer. Then, in ONE turn, say that reaction and continue with the step the reply gives "
        "you. Never ask a question of your own before calling it."),
    parameters=types.Schema(type="OBJECT", properties={
        "reaction": types.Schema(type="STRING", description=(
            "The one short sentence (Hebrew) you will say first: a warm reaction to what he just said -- his "
            "words, his story, his answer. Not a generic 'let's go on'.")),
        "done": types.Schema(type="STRING", description="Which step you finished (English, a few words)."),
        "how_it_went": types.Schema(type="STRING", description="One short English sentence."),
    }, required=["reaction", "done"]),
)
TOKEN_REACTIONS = ("בוא נמשיך", "בוא נעבור", "יופי", "טוב", "אוקיי", "מצוין", "נהדר", "כל הכבוד")


def reply_reaction(step_text: str, args: dict) -> tuple[str, str]:
    reaction = str(args.get("reaction") or "").strip()
    if len(_words(reaction)) < 3 or reaction.strip(" .!") in TOKEN_REACTIONS:
        return "held_reaction", ("Not yet: your reaction is missing. Call next_step again with one short sentence "
                                 "about what he just said.")
    return "advanced", f'Say first: "{reaction}"\nThen CURRENT STEP: {step_text}'


VARIANTS = {
    "current": {"subs": [], "tool": NEXT_STEP_TOOL, "reply": reply_current},
    # Plan 18 A, tested 23.10 and shelved: next_step with a required `reaction`, echoed by the page's
    # reply. The real failure didn't reproduce in text (today's prompt reacted too), and it brought a
    # reaction said twice, a turn with only the reaction, and an English "understood.".
    "reaction_param": {"subs": [], "tool": REACTION_TOOL, "reply": reply_reaction},
}


# --- the replayed moment ----------------------------------------------------------------------------

def _sections(text: str) -> dict[str, str]:
    out = {}
    for part in ("\n\n" + text).split("\n\n## ")[1:]:
        title, _, body = part.partition("\n")
        out[title.strip()] = body
    return out


def session_prompt(saved: str, subs: list[tuple[str, str]]) -> str:
    """The session's archived prompt, its fixed sections from today's template, then the variant."""
    today = _sections(render_tutor_prompt(steps=overview([])).text)
    parts = []
    for title, body in _sections(saved).items():
        parts.append(f"## {title}\n{today[title] if title in FIXED and title in today else body}")
    text = "\n\n".join(parts)
    for old, new in subs:
        if old not in text:
            raise ValueError(f"variant text not found in the prompt: {old[:60]}")
        text = text.replace(old, new)
    return text


def moment(session: dict, turns: list[dict], cut: int) -> dict:
    """The history before her flagged turn turns[cut], his answer to send, and the step state."""
    agenda = session.get("agenda") or []
    done = session.get("steps_done") or []
    start = cut  # his last answer: the patient turns just before hers
    while start > 0 and turns[start - 1]["speaker"] == "patient":
        start -= 1
    his = " ".join(t["text"] for t in turns[start:cut]).strip()
    t_his = turns[start]["t_start_s"] if start < cut else turns[cut].get("t_start_s", 0)
    hist = [types.Content(role="user", parts=[types.Part(text=START_NOTE.format(step=agenda[0]["text"]))])]
    k = 0  # steps done in the history
    for t in turns[:start]:
        while k < len(done) and done[k].get("at_s", 0) <= t.get("t_start_s", 0) + 1 and t["speaker"] == "tutor" \
                and done[k].get("at_s", 0) < t_his:
            d = done[k]
            nxt = agenda[k + 1]["text"] if k + 1 < len(agenda) else session.get("agenda_after", "")
            hist.append(types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
                id=f"s{k}", name="next_step", args={"done": d.get("done", ""), "how_it_went": d.get("how_it_went", "")}))]))
            hist.append(types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
                id=f"s{k}", name="next_step", response={"result": f"CURRENT STEP: {nxt}"}))]))
            k += 1
        if t.get("not_played"):
            continue
        role = "model" if t["speaker"] == "tutor" else "user"
        if hist[-1].role == role and hist[-1].parts[-1].text is not None:
            hist[-1].parts[-1].text += " " + t["text"]
        else:
            hist.append(types.Content(role=role, parts=[types.Part(text=t["text"])]))
    last_change = done[k - 1].get("at_s", 0) if k else 0
    answers = sum(1 for t in turns[:cut] if t["speaker"] == "patient" and t.get("t_start_s", 0) >= last_change)
    asked = [(_words(q), q) for t in turns[:start] if t["speaker"] == "tutor" for q in _questions(t["text"])]
    return {"history": hist, "his": his, "step": k, "answers": max(1, answers), "asked": asked,
            "agenda": agenda, "after": session.get("agenda_after", "")}


async def replay(client, model, cfg, m: dict, reply) -> dict:
    """Her turn after his answer, live, with the page's rules; returns what she said and did."""
    queue: asyncio.Queue = asyncio.Queue()
    said, calls, guards, step = "", [], 0, m["step"]

    def text_of(msg):
        sc = msg.server_content
        return sc.output_transcription.text if sc and sc.output_transcription and sc.output_transcription.text else ""

    async with client.aio.live.connect(model=model, config=cfg) as session:
        async def reader():
            while True:
                async for msg in session.receive():
                    await queue.put(msg)

        task = asyncio.create_task(reader())
        await session.send_client_content(turns=m["history"], turn_complete=False)
        await session.send_realtime_input(text=m["his"])
        try:
            while True:
                msg = await asyncio.wait_for(queue.get(), 30)
                said += text_of(msg)
                if msg.tool_call:
                    for fc in msg.tool_call.function_calls:
                        end = time.time() + 1.2  # the page waits for her transcript (16.10)
                        while time.time() < end:
                            try:
                                said += text_of(await asyncio.wait_for(queue.get(), max(0.05, end - time.time())))
                            except asyncio.TimeoutError:
                                break
                        args = dict(fc.args or {})
                        if fc.name != "next_step":
                            kind, text = "other", "ok"
                        elif "?" in said and guards < 2:
                            guards += 1
                            kind, text = "held_question", HOLD_QUESTION
                        elif m["answers"] < (m["agenda"][step].get("min_answers", 2) if step < len(m["agenda"]) else 0):
                            kind, text = "held_answers", HOLD_ANSWERS
                        else:
                            nxt = m["agenda"][step + 1]["text"] if step + 1 < len(m["agenda"]) else m["after"]
                            kind, text = reply(nxt, args)
                            if kind == "advanced":
                                step += 1
                        calls.append({"kind": kind, "args": args, "said_before": said})
                        said += f" <{fc.name}:{kind}> "
                        await session.send_tool_response(function_responses=[types.FunctionResponse(
                            id=fc.id, name=fc.name, response={"result": text})])
                sc = msg.server_content
                if sc and sc.turn_complete and not said.rstrip().endswith(">"):
                    break
        except asyncio.TimeoutError:
            said += " [timeout]"
        task.cancel()
    return {"said": said, "calls": calls, "advanced": any(c["kind"] == "advanced" for c in calls)}


def repeats(asked: list, said: str) -> list[str]:
    out = []
    for q in _questions(said):
        w = _words(q)
        if any(len(w & prev) / max(1, min(len(w), len(prev))) >= REPEAT_OVERLAP for prev, _ in asked):
            out.append(q)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--account", required=True)
    ap.add_argument("--sessions", type=int, default=10)
    ap.add_argument("--min-version", default="3.3")
    ap.add_argument("--variants", default="current")
    ap.add_argument("--issues", default="no_reaction,double_q,repeated")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0, help="at most this many points (0: all)")
    ap.add_argument("--only", default="", help="only these points: <session id>:<turn index>, comma-separated")
    ap.add_argument("--out", required=True, help="a folder for the run logs (outside the repo); rerunning with "
                                                 "the same folder skips the replays already done")
    ap.add_argument("--parallel", type=int, default=5, help="replays at a time (each is its own Live session)")
    args = ap.parse_args()

    settings = get_settings()
    store = FirestoreSessionStore()
    sessions = {s["id"]: s for s in load_sessions(store, args.account, args.sessions, args.min_version)}
    points = [p for p in measure(store, args.account, list(sessions.values()))["points"]
              if p["issue"] in args.issues.split(",")]
    turns_of = {sid: session_turns(store, args.account, sid) for sid in {p["sid"] for p in points}}
    # a flagged turn with no answer of his just before it (after a silence) has nothing to replay
    points = [p for p in points if p["i"] and turns_of[p["sid"]][p["i"] - 1]["speaker"] == "patient"]
    if args.only:
        points = [p for p in points if f"{p['sid']}:{p['i']}" in args.only.split(",")]
    if args.limit:
        points = points[:args.limit]
    client = genai.Client(api_key=settings.gemini_api_key)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = out / "replays.jsonl"  # one line per finished replay: a stopped run picks up from here
    done = {}
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["key"]] = r
    jobs = []  # (key, label, point, moment, config, variant, run)
    for n, p in enumerate(points, 1):
        turns = turns_of[p["sid"]]
        m = moment(sessions[p["sid"]], turns, p["i"])
        m["was"] = turns[p["i"]]["text"]
        saved = (store.get_session_prompt(args.account, p["sid"]) or {}).get("text", "")
        for name in args.variants.split(","):
            v = VARIANTS[name]
            prompt = session_prompt(saved, v["subs"])
            # the key holds the prompt and the tool: after a prompt change the point is replayed again
            version = hashlib.sha1((prompt + json.dumps(v["tool"].model_dump(mode="json"), sort_keys=True))
                                   .encode("utf-8")).hexdigest()[:12]
            cfg = types.LiveConnectConfig(
                response_modalities=[types.Modality.AUDIO], system_instruction=prompt,
                output_audio_transcription=types.AudioTranscriptionConfig(),
                history_config=types.HistoryConfig(initial_history_in_client_content=True),
                tools=[types.Tool(function_declarations=[END_SESSION_TOOL, v["tool"]])])
            for run in range(1, args.runs + 1):
                key = f"{p['sid']}:{p['i']}|{name}|{run}|{version}"
                jobs.append((key, f"{n}/{len(points)} {p['issue']} {name} #{run}", p, m, cfg, name, run))
    todo = [j for j in jobs if j[0] not in done]
    print(f"{len(jobs)} replays: {len(jobs) - len(todo)} already done (in {log}), {len(todo)} to run, "
          f"{args.parallel} at a time", flush=True)

    async def run_all():
        gate = asyncio.Semaphore(args.parallel)

        async def one(key, label, p, m, cfg, name, run):
            async with gate:
                try:
                    r = await replay(client, settings.live_model, cfg, m, VARIANTS[name]["reply"])
                except Exception as exc:  # noqa: BLE001 -- one failed replay doesn't stop the rest
                    print(f"[{label}] failed: {exc!s:.150} (not saved: it runs again next time)", flush=True)
                    return
            if "[timeout]" in r["said"]:
                print(f"[{label}] timed out (not saved: it runs again next time)", flush=True)
                return
            r.update(key=key, point=p, variant=name, run=run, his=m["his"], was=m["was"],
                     repeated=repeats(m["asked"], r["said"]))
            with log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
            done[key] = r
            print(f"[{label}] HE: {m['his'][:60]}\n    SHE: {r['said'].strip()[:220]}", flush=True)

        await asyncio.gather(*(one(*j) for j in todo))

    if todo:
        asyncio.run(run_all())
    results = [done[j[0]] for j in jobs if j[0] in done]
    if len(results) < len(jobs):
        print(f"!! {len(jobs) - len(results)} replays didn't finish: run the same command again to complete them")
    # the judge: her whole turn, the tool markers dropped
    clean = [" ".join(w for w in r["said"].split() if not w.startswith("<")) for r in results]
    for r, v in zip(results, judge_many([(r["his"], c) for r, c in zip(results, clean)])):
        r["verdict"] = v.model_dump()
    (out / "replay.json").write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    print("\n== results (per variant)")
    for name in args.variants.split(","):
        rs = [r for r in results if r["variant"] == name]
        nr = [r for r in rs if r["point"]["issue"] == "no_reaction"]
        adv = [r for r in nr if r["advanced"]]
        dq = [r for r in rs if r["point"]["issue"] == "double_q"]
        rp = [r for r in rs if r["point"]["issue"] == "repeated"]
        print(f"  {name}:")
        print(f"    no reaction points : reacted {sum(r['verdict']['reacted'] for r in adv)}/{len(adv)} step changes"
              f" (replays that stayed in the step: {len(nr) - len(adv)} of {len(nr)})")
        print(f"    double-q points    : still 2+ questions {sum(r['verdict']['real_questions'] >= 2 for r in dq)}/{len(dq)}")
        print(f"    repeated points    : asked again {sum(bool(r['repeated']) for r in rp)}/{len(rp)}")
        print(f"    all replays        : double questions {sum(r['verdict']['real_questions'] >= 2 for r in rs)}/{len(rs)},"
              f" read aloud {sum(r['verdict']['reads_instructions'] for r in rs)}, timeouts {sum('[timeout]' in r['said'] for r in rs)}")
    print(f"\nruns saved -> {out / 'replay.json'}")


if __name__ == "__main__":
    main()
