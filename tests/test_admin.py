"""Caregiver-only reset: forget memory / delete everything."""

from conftest import DAD, TOMER, auth


def seed(env, pid=DAD):
    sid = env.client.post("/api/session/start", headers=auth("tok-dad" if pid == DAD else "tok-tomer")).json()["session_id"]
    env.store.save_memory(pid, sid, {"memory_prompt": f"memory of {pid}", "word_bank": {"טבריה": {}},
                                     "sessions_processed": 1}, None)
    env.store.add_flag(pid, sid, {"kind": "distress", "severity": "low", "evidence": "x"})
    return sid


def reset(env, email, scope, confirm=None, token="tok-tomer"):
    return env.client.post(f"/api/caregiver/{email}/reset", headers=auth(token),
                           json={"scope": scope, "confirm_email": confirm or email})


def test_only_caregivers_can_use_admin(env):
    assert env.client.get("/api/caregiver/accounts", headers=auth("tok-dad")).status_code == 403
    assert reset(env, DAD, "memory", token="tok-dad").status_code == 403
    assert env.client.get("/api/caregiver/accounts").status_code == 401


def test_me_tells_the_page_who_is_a_caregiver(env):
    assert env.client.get("/api/me", headers=auth("tok-tomer")).json()["is_caregiver"] is True
    assert env.client.get("/api/me", headers=auth("tok-dad")).json()["is_caregiver"] is False


def test_accounts_overview(env):
    seed(env, DAD)
    accounts = {a["email"]: a for a in env.client.get("/api/caregiver/accounts", headers=auth("tok-tomer")).json()["accounts"]}
    assert set(accounts) == {DAD, TOMER}
    assert accounts[DAD] == {"email": DAD, "sessions": 1, "has_memory": True, "sessions_processed": 1, "words": 1}
    assert accounts[TOMER]["has_memory"] is False


def test_forget_memory_keeps_transcripts_and_other_accounts(env):
    dad_sid = seed(env, DAD)
    seed(env, TOMER)
    r = reset(env, DAD, "memory")
    assert r.status_code == 200 and r.json()["deleted_sessions"] == 0
    assert env.store.get_memory(DAD) is None
    assert env.store.get_session(DAD, dad_sid) is not None  # transcripts kept
    assert env.store.get_memory(TOMER)["memory_prompt"] == f"memory of {TOMER}"  # untouched
    # the next session starts like a first meeting
    from conftest import FakeAuthTokens
    env.client.post("/api/session/start", headers=auth("tok-dad"))
    instruction = FakeAuthTokens.last_config.live_connect_constraints.config.system_instruction.parts[0].text
    assert "WHAT YOU REMEMBER" not in instruction


def test_delete_everything_for_one_account(env):
    dad_sid = seed(env, DAD)
    tomer_sid = seed(env, TOMER)
    r = reset(env, DAD, "everything")
    assert r.json()["deleted_sessions"] == 1
    assert env.store.get_session(DAD, dad_sid) is None and env.store.get_memory(DAD) is None
    assert not [f for f in env.store.flags if f["pid"] == DAD]
    assert env.store.get_session(TOMER, tomer_sid) is not None  # other account untouched


def test_reset_requires_exact_confirmation_and_a_known_account(env):
    seed(env, DAD)
    assert reset(env, DAD, "memory", confirm="tomer@example.com").status_code == 400
    assert reset(env, "stranger@example.com", "memory").status_code == 404
    assert reset(env, DAD, "nuke").status_code == 422
    assert env.store.get_memory(DAD) is not None  # nothing happened
    assert reset(env, DAD.upper(), "memory", confirm=f"  {DAD} ").status_code == 200  # case/space tolerant


def test_reset_backs_up_the_memory_first(env):
    env.configure(prompt_archive_uri="gs://bucket/debug/prompts")
    seed(env, DAD)
    backup = reset(env, DAD, "everything").json()["backup"]
    assert backup.startswith(f"gs://bucket/debug/memory-backups/{DAD}/") and backup.endswith("-everything.json")
    assert f"memory of {DAD}" in env.archived[backup]
