"""Per-account records, the memory update on /end, and the hourly sweep."""

from app.schemas import ConsolidatedMemory
from conftest import DAD, TOMER, auth
from fake_llm import FakeClient, server_error, text, tool_calls

TALK = [
    {"seq": 0, "speaker": "tutor", "text": "שלום! על מה נדבר?", "t_start_s": 1},
    {"seq": 1, "speaker": "patient", "text": "על הנכדים", "live_text": "על הנכדים", "t_start_s": 4},
    {"seq": 2, "speaker": "tutor", "text": "ספר לי עליהם", "t_start_s": 8},
    {"seq": 3, "speaker": "patient", "text": "יש לי שלושה נכדים", "live_text": "יש לי שלושה נכדים", "t_start_s": 12},
]


def consolidated(prompt):
    return text("{}", parsed=ConsolidatedMemory(memory_prompt=prompt, focus_next_session=["ask about the grandchildren"]))


def plan_reply():
    from app.schemas import ClassPlan
    plan = ClassPlan(
        plan_type="regular",
        primary_goal={"type": "name_retrieval", "description": "Names of his grandchildren and places."},
        probe=[{"target": "טבריה", "kind": "untreated", "elicit": "העיר על הכנרת"},
               {"target": "זכרון יעקב", "kind": "untreated", "elicit": "המושבה על הכרמל עם היקבים"},
               {"target": "עכו", "kind": "untreated", "elicit": "העיר העתיקה עם החומות"}],
        homework="Think of a place to tell me about.",
    )
    return text("{}", parsed=plan)


def talk(env, token="tok-dad", turns=TALK):
    sid = env.client.post("/api/session/start", headers=auth(token)).json()["session_id"]
    env.client.post(f"/api/session/{sid}/turns", headers=auth(token), json={"turns": turns})
    return sid


def sweep(env, token="oidc-scheduler"):
    return env.client.post("/internal/memory/sweep", headers={"Authorization": f"Bearer {token}"})


# ---- separate records per account --------------------------------------------------------

def test_each_account_has_its_own_sessions_and_memory(env):
    env.llm = FakeClient(
        tool_calls(("update_memory", {"section": "personal_facts", "op": "add", "item": "Has three grandchildren"})),
        text("done"), consolidated("He has three grandchildren."),
    )
    env.configure()
    dad_sid = talk(env, "tok-dad")
    assert env.client.post(f"/api/session/{dad_sid}/end", headers=auth("tok-dad"),
                           json={"reason": "tutor_goodbye"}).json()["memory_status"] == "done"

    env.llm = FakeClient(text("done"), consolidated("Tomer's test memory."))
    env.configure()
    tomer_sid = talk(env, "tok-tomer")
    env.client.post(f"/api/session/{tomer_sid}/end", headers=auth("tok-tomer"), json={"reason": "end_button"})

    assert env.store.get_memory(DAD)["memory_prompt"] == "He has three grandchildren."
    assert env.store.get_memory(TOMER)["memory_prompt"] == "Tomer's test memory."
    assert env.store.get_session(DAD, dad_sid) and env.store.get_session(DAD, tomer_sid) is None
    assert env.store.get_session(TOMER, tomer_sid)["user_email"] == TOMER


def test_starting_a_session_only_abandons_your_own_open_sessions(env):
    dad_sid = talk(env, "tok-dad")
    talk(env, "tok-tomer")  # Tomer starts while Dad's session is still open
    assert env.store.get_session(DAD, dad_sid)["status"] == "active"


# ---- /end runs the memory update -----------------------------------------------------------

def test_end_runs_the_memory_update_then_builds_the_next_plan(env):
    env.llm = FakeClient(text("nothing to add"), consolidated("He talked about his grandchildren."), plan_reply())
    env.configure()
    sid = talk(env)
    r = env.client.post(f"/api/session/{sid}/end", headers=auth(), json={"reason": "tutor_goodbye"})
    assert r.json() == {"status": "ended", "memory_status": "done", "plan_status": "done"}
    assert env.store.get_session(DAD, sid)["memory_status"] == "done"
    assert env.store.get_next_plan(DAD)["primary_goal"]["type"] == "name_retrieval"


def test_end_still_succeeds_when_the_models_are_down(env):
    env.llm = FakeClient(*[server_error() for _ in range(6)])
    env.configure()
    sid = talk(env)
    r = env.client.post(f"/api/session/{sid}/end", headers=auth(), json={"reason": "tutor_goodbye"})
    assert r.status_code == 200 and r.json()["memory_status"] == "failed"
    assert env.store.get_session(DAD, sid)["status"] == "ended"  # the session itself is saved


# ---- the hourly sweep -------------------------------------------------------------------------

def test_sweep_rejects_everyone_but_the_scheduler(env):
    assert sweep(env, token="").status_code == 401
    assert sweep(env, token="forged").status_code == 401
    assert sweep(env, token="oidc-other").status_code == 403
    # a signed-in user's Firebase token isn't accepted here either
    assert env.client.post("/internal/memory/sweep", headers=auth("tok-tomer")).status_code == 401
    env.configure(sweeper_sa_email="")
    assert sweep(env).status_code == 503


def test_sweep_processes_abandoned_and_failed_sessions(env):
    abandoned = talk(env)  # tab closed: never ended
    talk(env, turns=[])  # Dad starts again -> the first is marked abandoned (memory pending)
    assert env.store.get_session(DAD, abandoned)["memory_status"] == "pending"

    env.llm = FakeClient(*[server_error() for _ in range(6)])  # models down during the sweep
    env.configure()
    assert sweep(env).json()["processed"] == {abandoned: "failed"}

    env.llm = FakeClient(text("ok"), consolidated("Recovered memory."), plan_reply())  # an hour later
    env.configure()
    assert sweep(env).json()["processed"] == {abandoned: "done", f"plan:{abandoned}": "done"}
    assert env.store.get_memory(DAD)["memory_prompt"] == "Recovered memory."
    assert sweep(env).json()["processed"] == {}  # nothing left


def test_sweep_respects_the_batch_limit(env):
    for _ in range(4):
        talk(env)  # each start abandons the previous one
    talk(env, turns=[])
    env.llm = FakeClient(*([text("ok"), consolidated("m")] * 4))
    env.configure(memory_sweep_batch=2)
    assert len(sweep(env).json()["processed"]) == 2
    assert len(sweep(env).json()["processed"]) == 2


# ---- the tutor uses the memory ------------------------------------------------------------------

def test_next_session_prompt_includes_this_accounts_memory_only(env):
    from conftest import FakeAuthTokens
    env.store.save_memory(DAD, "s0", {"memory_prompt": "Last session: his trip to Tiberias.",
                                      "focus_next_session": ["names of places"]}, None)
    env.store.save_memory(TOMER, "s1", {"memory_prompt": "Tomer likes Witcher 3."}, None)
    env.client.post("/api/session/start", headers=auth("tok-dad"))
    instruction = FakeAuthTokens.last_config.live_connect_constraints.config.system_instruction.parts[0].text
    assert "## WHAT YOU REMEMBER FROM PREVIOUS SESSIONS" in instruction
    assert "his trip to Tiberias" in instruction and "- names of places" in instruction
    assert "Witcher" not in instruction  # another account's memory never leaks in


def test_first_session_has_no_memory_section(env):
    from conftest import FakeAuthTokens
    env.client.post("/api/session/start", headers=auth("tok-dad"))
    instruction = FakeAuthTokens.last_config.live_connect_constraints.config.system_instruction.parts[0].text
    assert "WHAT YOU REMEMBER" not in instruction


# ---- debug archive of the exact tutor prompt ----------------------------------------------------

def test_each_session_archives_its_exact_prompt(env):
    from conftest import FakeAuthTokens
    env.configure(prompt_archive_uri="gs://bucket/debug/prompts/")
    env.store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee."}, None)
    sid = env.client.post("/api/session/start", headers=auth("tok-dad")).json()["session_id"]
    uri = env.store.get_session(DAD, sid)["prompt_uri"]
    # readable name: <Israel date_time>_<plan>_<sid8>.md (memory but no plan yet -> "no-plan")
    assert uri.startswith(f"gs://bucket/debug/prompts/{DAD}/") and uri.endswith(f"_no-plan_{sid[:8]}.md")
    sent = FakeAuthTokens.last_config.live_connect_constraints.config.system_instruction.parts[0].text
    assert sent in env.archived[uri]  # exactly what Gemini got
    assert "He loves the Galilee." in env.archived[uri] and f"**account:** {DAD}" in env.archived[uri]


def test_archive_off_or_failing_never_blocks_a_session(env):
    sid = env.client.post("/api/session/start", headers=auth()).json()["session_id"]  # off by default
    assert "prompt_uri" not in env.store.get_session(DAD, sid) and env.archived == {}

    def boom(uri, text):
        raise OSError("bucket unreachable")

    env.configure(prompt_archive_uri="gs://bucket/debug/prompts")
    from app.main import app, get_prompt_archive
    from app.prompt_archive import PromptArchive
    app.dependency_overrides[get_prompt_archive] = lambda: PromptArchive("gs://bucket/x", upload=boom)
    r = env.client.post("/api/session/start", headers=auth())
    assert r.status_code == 200 and "prompt_uri" not in env.store.get_session(DAD, r.json()["session_id"])
