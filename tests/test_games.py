import datetime as dt

from app.games import (
    game_link,
    games_snapshot,
    profile_for,
    recent_games_line,
    render_games_for_plan,
)

NOW = dt.datetime(2026, 10, 4, 12, 0, tzinfo=dt.timezone.utc)


def day(n):  # n days before NOW
    return (NOW - dt.timedelta(days=n)).isoformat()


class FakeUpstash:
    def __init__(self, data, fail=False):
        self.data, self.fail, self.calls = data, fail, []

    def scan(self, pattern):
        if self.fail:
            raise OSError("upstash down")
        prefix = pattern.rstrip("*")
        return sorted(k for k in self.data if k.startswith(prefix))

    def get_json(self, key):
        self.calls.append(key)
        return self.data.get(key)


DATA = {
    "efraim:scramble_progress_v1": {"sessions": [
        {"id": "a", "date": day(20), "category": "places", "words_solved_count": 3, "hints_used": 4},
        {"id": "b", "date": day(10), "category": "places", "words_solved_count": 4, "hints_used": 3},
        {"id": "c", "date": day(5), "category": "places", "words_solved_count": 6, "hints_used": 1},
        {"id": "d", "date": day(2), "category": "food", "words_solved_count": 7, "hints_used": 1},
        {"id": "e", "date": day(1), "category": "places", "words_solved_count": 8, "hints_used": 0},
    ]},
    "efraim:progress_v1": {"sessions": [{"id": "x", "date": day(40), "best_length": 4, "rounds_played": 4}]},
    "efraim:engagement_v1": {"visit_dates": [day(40)[:10], day(2)[:10], day(1)[:10]]},
    "efraim:puzzle_progress_v1": {"sessions": [{"id": "n", "date": day(0), "puzzles_done": 2}]},  # a NEW game
    "tomer:scramble_progress_v1": {"sessions": [{"id": "t", "date": day(0), "words_solved_count": 99}]},
}


def test_snapshot_discovers_known_and_new_games_with_trends():
    snap = games_snapshot(FakeUpstash(DATA), "efraim", NOW)
    by_key = {g.key: g for g in snap.games}
    assert set(by_key) == {"scramble_progress_v1", "progress_v1", "puzzle_progress_v1"}
    scramble = by_key["scramble_progress_v1"]
    assert scramble.id == "scramble" and scramble.known and scramble.route == "/scramble"
    assert (scramble.sessions_total, scramble.sessions_7d, scramble.sessions_30d, scramble.days_since_last) == (5, 3, 5, 1)
    assert scramble.trends["words_solved_count"] == {"recent": 7.0, "earlier": 3.5}
    assert scramble.trends["hints_used"] == {"recent": 0.7, "earlier": 3.5}
    assert "id" not in scramble.recent_sessions[0]
    new = by_key["puzzle_progress_v1"]
    assert not new.known and new.id == "puzzle_progress_v1"  # still included
    assert snap.visit_days_30 == 2
    assert snap.games[0].key == "puzzle_progress_v1"  # most recently played first


def test_profiles_never_mix():
    snap = games_snapshot(FakeUpstash(DATA), "efraim", NOW)
    assert all(99 not in [s.get("words_solved_count") for s in g.recent_sessions] for g in snap.games)
    tomer = games_snapshot(FakeUpstash(DATA), "tomer", NOW)
    assert [g.key for g in tomer.games] == ["scramble_progress_v1"]


def test_upstash_down_never_raises():
    snap = games_snapshot(FakeUpstash(DATA, fail=True), "efraim", NOW)
    assert snap.error and snap.games == []
    assert render_games_for_plan(snap) == "(games data unavailable right now)"
    assert recent_games_line(snap) == ""


def test_remote_catalog_wins_when_published():
    data = dict(DATA)
    data["games_catalog_v1"] = {"games": [{"id": "puzzle", "key": "puzzle_progress_v1", "name_he": "פאזל",
                                           "route": "/puzzle", "skills": ["x"]}]}
    snap = games_snapshot(FakeUpstash(data), "efraim", NOW)
    puzzle = next(g for g in snap.games if g.key == "puzzle_progress_v1")
    assert puzzle.known and puzzle.name_he == "פאזל"


def test_render_for_plan_and_recent_line():
    snap = games_snapshot(FakeUpstash(DATA), "efraim", NOW)
    text = render_games_for_plan(snap)
    assert "scramble (מילים מבולגנות): 5 sessions" in text
    assert "words_solved_count 7.0 vs 3.5" in text
    assert "NEW game, not in the catalog" in text
    line = recent_games_line(snap)
    assert "- מילים מבולגנות (yesterday): category \"places\"" in line
    assert "סיימון" not in line  # played 40 days ago: not "recent"


def test_profile_mapping_and_links():
    mapping = "Dad@Example.com=efraim, me@example.com = tomer"
    assert profile_for("dad@example.com", mapping) == "efraim"
    assert profile_for("me@example.com", mapping) == "tomer"
    assert profile_for("stranger@example.com", mapping) is None
    assert game_link("https://simon.example/", "/scramble", "efraim") == "https://simon.example/scramble?user=efraim"


def test_recent_line_lists_the_actual_words_he_played():
    data = {"efraim:scramble_progress_v1": {"sessions": [
                {"id": "a", "date": day(0), "category": "כלי עבודה", "words_shown": ["פטיש", "מברג", "מסמר"]}]},
            "efraim:change_word_progress_v1": {"sessions": [
                {"id": "b", "date": day(1), "pairs_shown": ["אפר>פאר", "שבע>עשב"]}]}}
    line = recent_games_line(games_snapshot(FakeUpstash(data), "efraim", NOW))
    assert 'מילים מבולגנות (today): category "כלי עבודה"; words: פטיש, מברג, מסמר' in line
    assert "החלפת מילה (yesterday): words: אפר → פאר, שבע → עשב" in line
