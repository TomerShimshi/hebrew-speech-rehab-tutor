"""Games in the app: /start line + homework links, builder context, recommendations, sweep."""

import datetime as dt

from app import llm
from app.agent.next_class import build_next_plan
from app.config import Settings
from app.games import games_snapshot
from app.schemas import ClassPlan
from app.store import InMemorySessionStore
from conftest import DAD, TOMER, FakeAuthTokens, auth
from fake_llm import FakeClient, text
from test_games import FakeUpstash

NOW = dt.datetime.now(dt.timezone.utc)
PROFILES = f"{DAD}=efraim,{TOMER}=tomer"
GAMES = {
    "efraim:scramble_progress_v1": {"sessions": [
        {"id": "a", "date": (NOW - dt.timedelta(days=1)).isoformat(), "category": "places",
         "words_solved_count": 6, "hints_used": 1}]},
    "efraim:engagement_v1": {"visit_dates": [(NOW - dt.timedelta(days=1)).date().isoformat()]},
    "tomer:change_word_progress_v1": {"sessions": [
        {"id": "t", "date": NOW.isoformat(), "changes_solved": 9}]},
}
PROBES = [{"target": "עכו", "kind": "untreated", "elicit": "העיר העתיקה"},
          {"target": "צפת", "kind": "untreated", "elicit": "עיר המקובלים"},
          {"target": "טבריה", "kind": "untreated", "elicit": "העיר על הכנרת"}]


def gen(client, models, contents, config=None):
    return llm.generate(client, models, contents, config, sleep=lambda s: None)


def plan(**over):
    fields = dict(plan_type="regular", primary_goal={"type": "name_retrieval", "description": "Places."},
                  probe=PROBES,
                  game_homework=[{"game_id": "scramble", "why": "places category, names practice"},
                                 {"game_id": "made_up_game", "why": "invented by the model"}],
                  games_note="He played scrambled words yesterday.",
                  games_app_feedback=[{"game_id": "scramble", "kind": "tune_difficulty", "title": "Harder places",
                                       "rationale": "1 hint only", "evidence": "hints_used 1"}])
    fields.update(over)
    return ClassPlan(**fields)


def with_games(env, **over):
    env.games_reader = FakeUpstash(GAMES)
    env.configure(simon_profiles=PROFILES, simon_app_url="https://simon.example", **over)


def instruction():
    return FakeAuthTokens.last_config.live_connect_constraints.config.system_instruction.parts[0].text


def test_start_tells_the_tutor_what_he_played_lately(env):
    with_games(env)
    env.client.post("/api/session/start", headers=auth())
    assert "## HIS GAMES APP" in instruction() and "מילים מבולגנות (yesterday)" in instruction()
    assert "bring it INTO the conversation" in instruction() and 'category "places"' in instruction()
    assert "החלפת מילה" not in instruction()  # Tomer's games never reach Dad's tutor


def test_no_games_config_means_no_games_section(env):
    env.client.post("/api/session/start", headers=auth())
    assert "## HIS GAMES APP" not in instruction()


def test_start_returns_homework_buttons_built_in_code(env):
    with_games(env)
    env.store.save_memory(DAD, "s0", {"memory_prompt": "x"}, None)
    p = plan(game_homework=[{"game_id": "scramble", "why": "names", "name_he": "מילים מבולגנות"}])
    env.store.save_next_plan(DAD, "s0", p.model_dump(mode="json"))
    body = env.client.post("/api/session/start", headers=auth()).json()
    assert body["game_homework"] == [{"name_he": "מילים מבולגנות", "why": "names",
                                      "url": "https://simon.example/scramble?user=efraim"}]
    assert "Game homework to suggest in the closing" in instruction()


def test_builder_gets_games_keeps_real_homework_and_saves_recommendations():
    store = InMemorySessionStore()
    store.save_memory(DAD, "s0", {"memory_prompt": "He loves the Galilee."}, None)
    sid = store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    client = FakeClient(text("{}", parsed=plan()))
    games = games_snapshot(FakeUpstash(GAMES), "efraim")
    settings = Settings(summary_model="primary", summary_fallback_models="fallback")
    assert build_next_plan(store, client, settings, DAD, sid, games=games, generate_fn=gen) == "done"
    assert "# GAMES" in client.requests[0]["contents"] and "scramble (מילים מבולגנות)" in client.requests[0]["contents"]
    saved = store.get_next_plan(DAD)
    assert [h["game_id"] for h in saved["game_homework"]] == ["scramble"]  # invented id dropped
    assert saved["game_homework"][0]["name_he"] == "מילים מבולגנות"
    assert saved["games_app_feedback"] == []  # stored separately
    # the same recommendation again -> one record, counted twice
    build_next_plan(store, FakeClient(text("{}", parsed=plan())), settings, DAD, sid, games=games, generate_fn=gen)
    recs = [r for (pid, _), r in store.recommendations.items() if pid == DAD]
    assert len(recs) == 1 and recs[0]["times_suggested"] == 2 and recs[0]["status"] == "new"


def test_sweep_rebuilds_a_plan_that_is_stale_after_new_games(env):
    with_games(env)
    env.store.save_memory(DAD, "s0", {"memory_prompt": "x"}, None)
    sid = env.store.create_session(DAD, user_email=DAD, model="m", prompt_version="v")
    env.store.save_next_plan(DAD, sid, plan().model_dump(mode="json"))
    env.store.next_plans[DAD]["built_at"] = NOW - dt.timedelta(days=3)  # built before he played
    env.llm = FakeClient(text("{}", parsed=plan(games_note="Rebuilt with fresh games.")))
    env.configure(simon_profiles=PROFILES, simon_app_url="https://simon.example")
    r = env.client.post("/internal/memory/sweep", headers={"Authorization": "Bearer oidc-scheduler"})
    assert r.json()["processed"] == {f"replan:{sid}": "done"}
    assert env.store.get_next_plan(DAD)["games_note"] == "Rebuilt with fresh games."
    # now fresh: the next sweep leaves it alone
    r = env.client.post("/internal/memory/sweep", headers={"Authorization": "Bearer oidc-scheduler"})
    assert r.json()["processed"] == {}


def test_upstash_down_never_blocks_a_session(env):
    env.games_reader = FakeUpstash(GAMES, fail=True)
    env.configure(simon_profiles=PROFILES)
    r = env.client.post("/api/session/start", headers=auth())
    assert r.status_code == 200 and "## HIS GAMES APP" not in instruction()
