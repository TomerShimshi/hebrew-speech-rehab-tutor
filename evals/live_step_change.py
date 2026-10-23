"""A/B test of the tutor's behavior around a step change, on Gemini Live (the real model and prompt).

Replays a real session's plan steps (from the database, with today's step rules), with his answers
simulated as text, and the page's rules simulated (the question guard with its ~1.2 s wait for the
transcript, the min answers per step). Each variant changes one rule of the tutor prompt (and the
next_step description); every run is saved as JSON for `evals/score_step_change.py`.

Text stands in for his voice, so this shows WHAT she says and in WHAT ORDER around a tool call -- not
audio behavior (freezes, transcript lag). See evals/README.md.

    python -m evals.live_step_change --account <email> --session <session id> --variant current --runs 3 --out <dir>

His answers: `--answers <file.json>` ({"<step kind>": ["answer 1", "answer 2"], ...}, used in order while
that step is current), e.g. real ones copied from the session -- keep such files out of git
(`*.local.json`). Otherwise a neutral simulated speaker answers.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from google import genai
from google.genai import types

from app.class_plan import session_steps
from app.config import get_settings
from app.deps import get_games_reader
from app.live_token import END_SESSION_TOOL, NEXT_STEP_TOOL
from app.patient_profile import account_profile
from app.schemas import ClassPlan
from app.session_prompt import build_session_prompt
from app.store import FirestoreSessionStore

# The rule under test, as the prompt renders it (the YAML block's indent dropped). A variant replaces it.
RULE_PREFIX = "- When his answer finishes the step:"
VARIANTS = {
    "current": None,  # the prompt as deployed
    "call_first_plain": (  # before 21.10: call first, then "react and continue" -- she skipped the reaction ~1/3
        "- When his answer finishes the step: FIRST call next_step (what you finished, how it went) --\n"
        "  before you say anything. Then, in ONE turn: react to his answer and continue with the new\n"
        "  step. If the reply says to wait for his answer, stop talking at once and wait.",
        None),
    "react_first": (  # tested 21.10: brought back double questions (5 in 16 step changes)
        "- When his answer finishes the step: FIRST say one short, warm reaction to what he just said\n"
        "  (one sentence about his words -- no question), THEN call next_step (what you finished, how it\n"
        "  went), and when the reply comes, go on in the same turn with the new step, bridged from his\n"
        "  words. If the reply says to wait for his answer, stop talking at once and wait.",
        "Call when his answer has just finished the CURRENT STEP -- right after your one-sentence reaction to it "
        "(no question), before anything else. Then, in the same turn, continue with the step the reply gives "
        "you. Never ask a question before calling it."),
}
NEUTRAL_SPEAKER = ("You play a friendly adult man in a Hebrew speaking practice. The tutor just said: {s} -- Reply "
                   "in Hebrew, ONE or two natural sentences, answering what she asked. Invent harmless everyday "
                   "details if needed.")
HOLD_QUESTION = ("Noted. You just asked him a question: stop talking now and wait for his answer. After his answer, "
                 "call next_step again.")
HOLD_ANSWERS = ("Not yet -- stay on this topic. Now: react to what he just said and ask ONE follow-up question about "
                "his own words. After his answer, call next_step again.")


def replace_rule(prompt: str, rule: str) -> str:
    start = prompt.index(RULE_PREFIX)
    end = prompt.index("\n- ", start + 1)  # the next bullet
    return prompt[:start] + rule + prompt[end:]


class Run:
    def __init__(self, client, model, cfg, steps, after, answers):
        self.client, self.model, self.cfg = client, model, cfg
        self.steps, self.after, self.answers = steps, after, answers
        self.step, self.count, self.guarded, self.guards = 0, 0, -1, 0
        self.log = {"transitions": [], "turns": []}
        self.queue: asyncio.Queue | None = None

    def page_reply(self, said_before_call: str) -> tuple[str, str]:
        """The page's answer to next_step (static/app.js), simplified."""
        i, needed = self.step, self.steps[self.step].get("min_answers", 2)
        if "?" in said_before_call and not (self.guarded == i and self.guards >= 2):
            self.guards = self.guards + 1 if self.guarded == i else 1
            self.guarded = i
            return "held_question", HOLD_QUESTION
        if self.count < needed:
            return "held_answers", HOLD_ANSWERS
        self.step += 1
        self.count = 0
        nxt = self.steps[self.step]["text"] if self.step < len(self.steps) else self.after
        return "advanced", f"CURRENT STEP: {nxt}"

    async def reader(self, session):
        # waiting on a queue can time out safely; cancelling a read of the stream itself closes it
        while True:
            async for msg in session.receive():
                await self.queue.put(msg)

    async def her_turn(self, session, his_last: str, t0: float) -> str:
        said, events = "", []

        async def nxt(timeout):
            return await asyncio.wait_for(self.queue.get(), timeout)

        def text_of(msg):
            sc = msg.server_content
            return sc.output_transcription.text if sc and sc.output_transcription and sc.output_transcription.text else ""

        try:
            while True:
                msg = await nxt(30)
                said += text_of(msg)
                if msg.tool_call:
                    for fc in msg.tool_call.function_calls:
                        end = time.time() + 1.2  # the page waits for her transcript before deciding (16.10)
                        while time.time() < end:
                            try:
                                said += text_of(await nxt(max(0.05, end - time.time())))
                            except asyncio.TimeoutError:
                                break
                        before = said
                        kind, text = self.page_reply(said) if fc.name == "next_step" else ("other", "ok")
                        events.append((kind, before))
                        said += f" <{fc.name}:{kind}> "
                        await session.send_tool_response(function_responses=[types.FunctionResponse(
                            id=fc.id, name=fc.name, response={"result": text})])
                sc = msg.server_content
                if sc and sc.turn_complete:
                    if said.rstrip().endswith(">"):
                        continue
                    break
        except asyncio.TimeoutError:
            said += " [timeout]"
        for kind, before in events:
            if kind == "advanced":
                to = self.steps[self.step]["kind"] if self.step < len(self.steps) else "after"
                self.log["transitions"].append({"his": his_last, "her": said, "said_before": before, "to_step": to})
        self.log["turns"].append({"his": his_last, "her": said})
        print(f"[{time.time() - t0:5.1f}s] SHE: {said.strip()[:200]}", flush=True)
        return said

    def his_answer(self, said: str) -> str:
        kind = self.steps[self.step]["kind"] if self.step < len(self.steps) else "after"
        queue = self.answers.get(kind)
        if queue:
            return queue.pop(0)
        r = self.client.models.generate_content(model="gemini-3.8-flash", contents=NEUTRAL_SPEAKER.format(s=said))
        return (r.text or "כן.").strip()

    async def go(self, max_answers: int = 14) -> dict:
        self.queue = asyncio.Queue()
        async with self.client.aio.live.connect(model=self.model, config=self.cfg) as session:
            task = asyncio.create_task(self.reader(session))
            t0 = time.time()
            await session.send_realtime_input(text=f"[The session starts. CURRENT STEP: {self.steps[0]['text']}]")
            said = await self.her_turn(session, "", t0)
            for _ in range(max_answers):
                if self.step >= len(self.steps):
                    break
                line = self.his_answer(said)
                self.count += 1
                print(f"[{time.time() - t0:5.1f}s] HIM: {line[:200]}", flush=True)
                await session.send_realtime_input(text=line)
                said = await self.her_turn(session, line, t0)
            task.cancel()
        self.log["reached_step"] = self.step
        return self.log


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--account", required=True, help="the account (email) whose session to replay")
    ap.add_argument("--session", help="the session id whose plan steps to replay")
    ap.add_argument("--plan", help="instead of a session: a plan file (JSON: plan_type, primary_goal, steps), e.g. "
                                   "evals/plans/missing_areas.json")
    ap.add_argument("--variant", default="current", choices=sorted(VARIANTS))
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--out", required=True, help="a folder for the run logs (outside the repo)")
    ap.add_argument("--answers", help="his answers per step kind (JSON; keep it out of git: *.local.json)")
    ap.add_argument("--max-answers", type=int, default=14, help="his answers per run at most")
    ap.add_argument("--skip", default="names_game", help="step kinds to leave out, comma-separated")
    args = ap.parse_args()

    settings = get_settings()
    store = FirestoreSessionStore()
    if not (args.session or args.plan):
        ap.error("give --session or --plan")
    plan = ClassPlan(**(json.loads(Path(args.plan).read_text(encoding="utf-8")) if args.plan
                        else store.get_session(args.account, args.session)["class_plan"]))
    steps = [s for s in session_steps(plan) if s["kind"] not in args.skip.split(",")]
    built = build_session_prompt(store, settings, args.account, account_profile(store, args.account).text,
                                 get_games_reader())
    prompt, tool = built.prompt.text, NEXT_STEP_TOOL
    if VARIANTS[args.variant]:
        rule, desc = VARIANTS[args.variant]
        prompt = replace_rule(prompt, rule)
        if desc:
            tool = NEXT_STEP_TOOL.model_copy(update={"description": desc})
    cfg = types.LiveConnectConfig(response_modalities=[types.Modality.AUDIO], system_instruction=prompt,
                                  output_audio_transcription=types.AudioTranscriptionConfig(),
                                  tools=[types.Tool(function_declarations=[END_SESSION_TOOL, tool])])
    client = genai.Client(api_key=settings.gemini_api_key)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for i in range(1, args.runs + 1):
        answers = json.loads(Path(args.answers).read_text(encoding="utf-8")) if args.answers else {}
        log = asyncio.run(Run(client, settings.live_model, cfg, steps, built.after_steps, answers).go(args.max_answers))
        log.update(variant=args.variant, run=i, session=args.session or args.plan)
        path = out / f"step_change_{args.variant}_{i}.json"
        path.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"run {i}: {len(log['transitions'])} step changes, reached step {log['reached_step']} -> {path}")


if __name__ == "__main__":
    main()
