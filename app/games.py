"""Read-only view of the Simon games app (sub-plan 06).

Simon stores each profile's progress in Upstash Redis under "<profile>:<key>", where every
game key holds {"sessions": [{id, date, ...fields}]}. We read it with Upstash's READ-ONLY
token (this app physically can't change Simon's data), discover games generically (any key
with a sessions list is a game -- new Simon games show up without code changes), and compute
trends in code so the model gets facts, not raw numbers to crunch.

Never raises: if Upstash is unreachable, sessions simply go ahead without games data.
"""

import datetime as dt
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from functools import lru_cache
from statistics import mean

import yaml

from app.config import REPO_ROOT

CATALOG_PATH = REPO_ROOT / "prompts" / "games_catalog.yaml"
REMOTE_CATALOG_KEY = "games_catalog_v1"  # if Simon ever publishes its own catalog, it wins
TIMEOUT_S = 4
RECENT_N = 3  # "recent" = the last 3 sessions of a game, compared with the ones before


def _log(message: str) -> None:
    print(f"[games] {message}", file=sys.stderr, flush=True)


# ---- Upstash (read-only REST) ---------------------------------------------------------------

class UpstashReader:
    def __init__(self, url: str, token: str, timeout: float = TIMEOUT_S):
        self._url = url.strip().strip("'\"").rstrip("/")
        self._token = token.strip().strip("'\"")
        self._timeout = timeout

    def _get(self, path: str):
        req = urllib.request.Request(f"{self._url}/{path}", headers={"Authorization": f"Bearer {self._token}"})
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read())["result"]

    def get_json(self, key: str) -> dict | None:
        raw = self._get(f"get/{urllib.parse.quote(key, safe=':')}")
        return json.loads(raw) if raw else None

    def scan(self, pattern: str, max_rounds: int = 20) -> list[str]:
        keys, cursor = [], "0"
        for _ in range(max_rounds):
            cursor, batch = self._get(f"scan/{cursor}/match/{urllib.parse.quote(pattern, safe=':*')}/count/200")
            keys += batch
            if str(cursor) == "0":
                break
        return sorted(set(keys))


# ---- catalog ------------------------------------------------------------------------------------

@lru_cache
def local_catalog() -> dict:
    return yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))


def load_catalog(reader) -> dict:
    try:
        remote = reader.get_json(REMOTE_CATALOG_KEY) if reader else None
        if isinstance(remote, dict) and isinstance(remote.get("games"), list):
            return remote
    except Exception:  # noqa: BLE001 -- fall back to our own copy
        pass
    return local_catalog()


# ---- account -> Simon profile -----------------------------------------------------------------

def profile_for(email: str, mapping: str) -> str | None:
    """SIMON_PROFILES="dad@x.com=efraim,me@x.com=tomer" -> the profile for this account."""
    for pair in mapping.split(","):
        account, _, profile = pair.partition("=")
        if account.strip().lower() == email.strip().lower() and profile.strip():
            return profile.strip()
    return None


def game_link(app_url: str, route: str, profile: str) -> str:
    return f"{app_url.rstrip('/')}{route}?user={urllib.parse.quote(profile)}"


# ---- snapshot ----------------------------------------------------------------------------------

@dataclass
class GameSnapshot:
    id: str
    key: str
    known: bool  # in the catalog (else: a new game, interpreted from its fields)
    name_he: str = ""
    route: str = ""
    skills: list[str] = field(default_factory=list)
    progress: str = ""
    speech_link: str = ""
    sessions_total: int = 0
    sessions_7d: int = 0
    sessions_30d: int = 0
    last_played: str | None = None  # ISO date
    days_since_last: int | None = None
    trends: dict[str, dict] = field(default_factory=dict)  # field -> {recent, earlier}
    recent_sessions: list[dict] = field(default_factory=list)


@dataclass
class GamesSnapshot:
    profile: str
    games: list[GameSnapshot] = field(default_factory=list)
    visit_days_30: int = 0
    last_visit: str | None = None
    error: str | None = None

    @property
    def latest_played(self) -> dt.datetime | None:
        dates = [g.last_played for g in self.games if g.last_played]
        return dt.datetime.fromisoformat(max(dates)) if dates else None


def _parse_date(value) -> dt.datetime | None:
    try:
        d = dt.datetime.fromisoformat(str(value))
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _trends(sessions: list[dict]) -> dict[str, dict]:
    numeric = sorted({k for s in sessions for k, v in s.items()
                      if isinstance(v, (int, float)) and not isinstance(v, bool)})
    out = {}
    recent, earlier = sessions[-RECENT_N:], sessions[:-RECENT_N][-10:]
    for name in numeric:
        r = [s[name] for s in recent if isinstance(s.get(name), (int, float))]
        e = [s[name] for s in earlier if isinstance(s.get(name), (int, float))]
        if r:
            out[name] = {"recent": round(float(mean(r)), 1), "earlier": round(float(mean(e)), 1) if e else None}
    return out


def _summarize(game_id: str, key: str, entry: dict | None, sessions: list[dict], now: dt.datetime) -> GameSnapshot:
    g = GameSnapshot(id=game_id, key=key, known=entry is not None)
    if entry:
        g.name_he, g.route = entry.get("name_he", ""), entry.get("route", "")
        g.skills = list(entry.get("skills", []))
        g.progress, g.speech_link = entry.get("progress", ""), entry.get("speech_link", "")
    dated = sorted(((d, s) for s in sessions if (d := _parse_date(s.get("date")))), key=lambda ds: ds[0])
    sessions = [s for _, s in dated]
    g.sessions_total = len(sessions)
    g.sessions_7d = sum(1 for d, _ in dated if (now - d).days < 7)
    g.sessions_30d = sum(1 for d, _ in dated if (now - d).days < 30)
    if dated:
        last = dated[-1][0]
        g.last_played, g.days_since_last = last.isoformat(), (now - last).days
    g.trends = _trends(sessions)
    g.recent_sessions = [{k: v for k, v in s.items() if k != "id"} for s in sessions[-RECENT_N:]]
    return g


def games_snapshot(reader, profile: str, now: dt.datetime | None = None) -> GamesSnapshot:
    """Every game this Simon profile has played, with trends. Never raises."""
    now = now or dt.datetime.now(dt.timezone.utc)
    snap = GamesSnapshot(profile=profile)
    try:
        catalog = load_catalog(reader)
        by_key = {g["key"]: g for g in catalog.get("games", [])}
        visits_key = catalog.get("visits_key", "engagement_v1")
        for full_key in reader.scan(f"{profile}:*"):
            key = full_key.split(":", 1)[1]
            data = reader.get_json(full_key) or {}
            if key == visits_key:
                dates = sorted(str(d) for d in data.get("visit_dates", []))
                snap.last_visit = dates[-1] if dates else None
                cutoff = (now.date() - dt.timedelta(days=30)).isoformat()
                snap.visit_days_30 = sum(1 for d in dates if d >= cutoff)
            elif isinstance(data.get("sessions"), list):
                entry = by_key.get(key)
                game_id = entry["id"] if entry else key
                snap.games.append(_summarize(game_id, key, entry, data["sessions"], now))
        snap.games.sort(key=lambda g: g.last_played or "", reverse=True)
    except Exception as exc:  # noqa: BLE001 -- games are a bonus; never break a session
        snap.error = f"{type(exc).__name__}: {exc!s:.150}"
        _log(f"snapshot for {profile} failed: {snap.error}")
    return snap


# ---- text for the models -----------------------------------------------------------------------

def render_games_for_plan(snap: GamesSnapshot | None) -> str:
    if snap is None:
        return "(no games account linked)"
    if snap.error:
        return "(games data unavailable right now)"
    if not snap.games:
        return f"(no games played yet; app opened on {snap.visit_days_30} of the last 30 days)"
    lines = [f"App opened on {snap.visit_days_30} of the last 30 days (last: {snap.last_visit or '?'})."]
    for g in snap.games:
        title = f"{g.id} ({g.name_he})" if g.known else f"{g.key} (NEW game, not in the catalog: interpret its fields)"
        lines.append(f"- {title}: {g.sessions_total} sessions; {g.sessions_7d} in the last 7 days, "
                     f"{g.sessions_30d} in 30; last played {g.days_since_last} day(s) ago.")
        if g.known:
            lines.append(f"    skills: {', '.join(g.skills)} | progress = {g.progress} | speech link: {g.speech_link}")
        if g.trends:
            lines.append("    trends (recent avg vs earlier avg): " + "; ".join(
                f"{k} {v['recent']} vs {v['earlier'] if v['earlier'] is not None else 'n/a'}" for k, v in g.trends.items()))
        if g.recent_sessions:
            lines.append(f"    last sessions: {json.dumps(g.recent_sessions, ensure_ascii=False, default=str)[:600]}")
    return "\n".join(lines)


WORD_FIELDS = ("words_shown", "pairs_shown", "base_words")  # fields holding the actual words


def _played_words(session: dict, limit: int = 10) -> list[str]:
    words = []
    for name in WORD_FIELDS:
        value = session.get(name)
        if isinstance(value, list):
            words += [str(w).replace(">", " → ") for w in value]
    return words[:limit]


def recent_games_line(snap: GamesSnapshot | None, days: int = 3) -> str:
    """Fresh facts for the tutor at /start (no LLM): what he played lately -- including the
    category and the actual words, so she can turn the game into conversation."""
    if not snap or snap.error or not snap.games:
        return ""
    recent = [g for g in snap.games if g.days_since_last is not None and g.days_since_last < days]
    if not recent:
        return ""
    lines = ["Recently, in the Simon games app:"]
    for g in recent:
        when = "today" if g.days_since_last == 0 else "yesterday" if g.days_since_last == 1 else f"{g.days_since_last} days ago"
        last = g.recent_sessions[-1] if g.recent_sessions else {}
        detail = []
        if last.get("category"):
            detail.append(f"category \"{last['category']}\"")
        words = _played_words(last)
        if words:
            detail.append("words: " + ", ".join(words))
        lines.append(f"- {g.name_he or g.key} ({when})" + (f": {'; '.join(detail)}" if detail else ""))
    return "\n".join(lines)
