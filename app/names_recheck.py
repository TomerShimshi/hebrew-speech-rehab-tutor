"""The names game rechecked from the session's recording, after the session.

The live model can mishear him (seen in a patient session: he said a name right, the game recorded
it as missed). Once both the memory update (the live results) and the recording's join are done --
whichever finishes second: /audio/finish, /end, or the hourly sweep -- one model call listens to the
recording and says, per name, what he said and whether he found it. Only CONFIDENT disagreements
change the score: the session's probe_results, the check-in set's result for this session, and one
`misheard` tutor_issue flag. An unclear recording changes nothing. The next plan is not rebuilt.

Never raises: a failure is recorded on the session (names_recheck=failed) and not retried.
"""

import sys

from google.genai import types

from app import check_in_set, telemetry
from app.agent.memory_update import _models
from app.config import Settings
from app.llm import generate
from app.schemas import ClassPlan, NamesHeard
from app.store import MEM_DONE

FOUND = ("uncued", "cued")  # a names-game result in which he found the name

INSTRUCTION = (
    "This is the recording of a Hebrew speech-practice session between a tutor (a synthetic voice) and a man "
    "with word-finding difficulty after a stroke. At some point she plays a short names game: she asks the "
    "questions below, one at a time, and he tries to say the name.\n\n"
    "{questions}\n\n"
    "For each question, find his reply in the recording and report:\n"
    "- target: the target name, copied exactly as written above;\n"
    "- heard: what he actually said in reply, in Hebrew (empty if he said nothing);\n"
    "- found: true if he said the target name himself before she said it -- a near pronunciation of the name "
    "counts, and so does a right second try after she asks him to repeat (\"תגיד שוב\"); false if he said a "
    "different word, gave up, or only repeated it after she said it;\n"
    "- confident: false when you are unsure -- the reply is unclear, cut off, or hard to hear.\n"
    "Leave out a question whose reply isn't in the recording."
)


def _log(message: str) -> None:
    print(f"[names_recheck] {message}", file=sys.stderr, flush=True)
    telemetry.note(f"[names_recheck] {message}")


def _norm(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _game_items(session: dict) -> list:
    try:
        game = ClassPlan(**session["class_plan"]).names_game if session.get("class_plan") else None
    except Exception:  # noqa: BLE001 -- an old/odd plan: no game to recheck
        return []
    return list(game.items) if game else []


def _flag(changed: list[dict]) -> dict:
    found = sum(c["found"] for c in changed)
    missed = len(changed) - found
    parts = ([f"{found} answer(s) scored as missed that he found"] if found else []) + \
            ([f"{missed} answer(s) scored as found that he missed"] if missed else [])
    return {"kind": "tutor_issue", "severity": "low", "issue": "misheard",
            "evidence": f"The recording disagreed with the live names game: {' and '.join(parts)}. "
                        "The score was corrected from the recording.",
            "tutor_said": " · ".join(c["question"] for c in changed),
            "he_said": " · ".join(c["heard"] for c in changed),
            "names": [c["target"] for c in changed]}


def recheck_names_game(store, client, audio, settings: Settings, pid: str, sid: str, *, generate_fn=generate) -> str:
    """Returns the session's names_recheck status: agreed | changed | skipped | failed | not_ready | not_claimed.
    The checks before the claim are cheap and quiet (no trace): the hooks call this on every session."""
    try:
        session = store.get_session(pid, sid) or {}
        if session.get("excluded"):  # left out (20.5): nothing learns from it; not stored, so a put-back can run it
            return "skipped"
        if session.get("memory_status") != MEM_DONE:
            return "not_ready"
        items = _game_items(session)
        targets = {_norm(i.target) for i in items}
        if not any(_norm(r.get("word", "")) in targets for r in session.get("probe_results") or []):
            if session.get("names_recheck") is None:
                store.update_session(pid, sid, {"names_recheck": "skipped"})
                return "skipped"
            return "not_claimed"
        if not session.get("audio_uri"):
            return "not_ready"
        if not store.claim_names_recheck(pid, sid):
            return "not_claimed"
    except Exception as exc:  # noqa: BLE001
        _log(f"{sid}: not checked: {type(exc).__name__}: {exc!s:.200}")
        return "failed"
    return _recheck(store, client, audio, settings, pid, sid, session, items, generate_fn=generate_fn)


@telemetry.job("names_recheck")
def _recheck(store, client, audio, settings: Settings, pid: str, sid: str, session: dict, items: list, *,
             generate_fn) -> str:
    """The claimed recheck: one model call, then only confident disagreements are applied."""
    targets = {_norm(i.target) for i in items}
    try:
        data = audio.load(session["audio_uri"])
        questions = "\n".join(f'{n}) question: "{i.elicit}" -- target: {i.target}' for n, i in enumerate(items, 1))
        result = generate_fn(
            client, _models(settings),
            [types.Part.from_bytes(data=data, mime_type=session.get("audio_type") or "audio/webm"),
             INSTRUCTION.format(questions=questions)],
            types.GenerateContentConfig(response_mime_type="application/json", response_schema=NamesHeard,
                                        temperature=0),
        )
        heard = result.response.parsed
        if not isinstance(heard, NamesHeard):
            heard = NamesHeard.model_validate_json(result.response.text)

        by_target = {_norm(h.target): h for h in heard.names}
        questions_by_target = {_norm(i.target): i.elicit for i in items}
        probe_results = [dict(r) for r in session.get("probe_results") or []]
        current_set = store.get_check_in_set(pid)
        changed, set_changed = [], False
        for r in probe_results:
            word = _norm(r.get("word", ""))
            h = by_target.get(word)
            if h is None or word not in targets or not h.confident or h.found == (r.get("result") in FOUND):
                continue
            new = "uncued" if h.found else "failed"
            r.update(live_result=r.get("result"), result=new, rechecked=True)
            changed.append({"target": r["word"], "question": questions_by_target.get(word, ""),
                            "heard": h.heard, "found": h.found})
            if current_set:
                set_changed |= check_in_set.correct_result(current_set, sid, r["word"], new)

        status = "changed" if changed else "agreed"
        fields = {"names_recheck": status, "names_recheck_heard": [h.model_dump() for h in heard.names],
                  "names_recheck_model": result.model}
        if changed:
            fields["probe_results"] = probe_results
        store.update_session(pid, sid, fields)
        if set_changed:
            store.save_check_in_set(pid, current_set)
        if changed:
            store.add_flag(pid, sid, _flag(changed))
        _log(f"{sid}: {status} ({len(changed)} of {len(heard.names)} name(s) corrected)")
        return status
    except Exception as exc:  # noqa: BLE001 -- recorded, never breaks /end, /audio/finish or the sweep
        _log(f"{sid}: FAILED {type(exc).__name__}: {exc!s:.300}")
        try:
            store.update_session(pid, sid, {"names_recheck": "failed",
                                            "names_recheck_error": f"{type(exc).__name__}: {exc!s:.300}"})
        except Exception:  # noqa: BLE001
            pass
        return "failed"
