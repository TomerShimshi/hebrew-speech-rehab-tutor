"""Research sub-agent (sub-plan 07): one generic clinical question -> sourced home-practice techniques.

Two phases, like the memory update:
  1. search: a tool loop with web_search (Tavily), bounded by our own counters
  2. findings: one structured-output call that sees only the search results

Then the code -- not the model -- enforces the guardrails: every technique must cite a URL a
search returned in THIS run, nothing medical survives, and no query may carry his names,
places or Hebrew text. Results are cached per account for 30 days. Never raises: the plan
builder gets a status ("ok", "cached", "no_findings", "rejected", "budget", "unavailable",
"failed") and builds the plan either way.
"""

import datetime as dt
import hashlib
import re
import sys
from collections.abc import Callable
from functools import lru_cache

import yaml
from google.genai import types

from app.agent.runner import Tool, run_tool_loop
from app.config import REPO_ROOT, Settings
from app.llm import generate
from app.research_sources import (
    SCOPES,
    TavilyUnavailable,
    has_hebrew,
    is_medical,
    is_trusted_domain,
    personal_terms_in,
    web_search,
)
from app.schemas import ResearchFindings
from app.store import SessionStore

PROMPT_PATH = REPO_ROOT / "prompts" / "research_agent.yaml"
MAX_TECHNIQUES = 3
QUESTION_CHARS = 300
# Capitalized words that are not about him (languages, the country, the apps).
NOT_PERSONAL = {"hebrew", "english", "arabic", "russian", "israel", "israeli", "simon", "gemini"}


def _log(message: str) -> None:
    print(f"[research] {message}", file=sys.stderr, flush=True)


@lru_cache
def load_prompt() -> dict:
    return yaml.safe_load(PROMPT_PATH.read_text(encoding="utf-8"))


def _models(settings: Settings) -> list[str]:
    fallbacks = [m.strip() for m in settings.summary_fallback_models.split(",") if m.strip()]
    return [settings.summary_model, *fallbacks]


def personal_terms(memory_raw: dict | None, profile_text: str = "", extra: tuple[str, ...] = ()) -> set[str]:
    """Names and places of his that must never reach a search engine.

    Hebrew text is rejected separately (has_hebrew), so this collects the Latin-script ones:
    capitalized words in the middle of a sentence ("his wife Rina", "lived in Haifa") from the
    profile and the memory, plus `extra` (the account name, his games profile).
    """
    memory_raw = memory_raw or {}
    texts = [profile_text, memory_raw.get("memory_prompt", ""), *memory_raw.get("focus_next_session", [])]
    for items in (memory_raw.get("sections") or {}).values():
        texts += [str(i) for i in items or []]
    terms = set()
    for text in texts:
        terms |= set(re.findall(r"(?<=[a-z0-9,;:)]\s)([A-Z][A-Za-z'\-]{2,})", text or ""))
    for value in extra:
        terms |= {p for p in re.split(r"[^A-Za-z]+", value or "") if len(p) >= 3}
    return {t for t in terms if t.lower() not in NOT_PERSONAL}


def normalize_question(question: str) -> str:
    return " ".join((question or "").split())[:QUESTION_CHARS]


def note_id(question: str) -> str:
    key = re.sub(r"[^a-z0-9 ]", "", normalize_question(question).lower())
    return hashlib.sha1(" ".join(key.split()).encode("utf-8")).hexdigest()[:16]


def _norm_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _public(note: dict, status: str) -> dict:
    """What the plan builder sees."""
    return {"status": status, "summary": note.get("summary", ""), "confidence": note.get("confidence", ""),
            "techniques": note.get("techniques", [])}


def _strip_medical_sentences(text: str) -> str:
    return " ".join(s for s in re.split(r"(?<=[.!?])\s+", text or "") if not is_medical(s))


def verify_findings(findings: ResearchFindings, returned: dict[str, dict]) -> tuple[list[dict], dict]:
    """Keeps only techniques sourced from this run's results and free of medical content."""
    by_norm = {_norm_url(u): u for u in returned}
    kept, dropped = [], {"unsourced": 0, "medical": 0, "over_limit": 0}
    for t in findings.techniques:
        url = by_norm.get(_norm_url(t.source_url))
        if url is None:
            dropped["unsourced"] += 1
            _log(f"dropped (source not returned by a search): {t.name!r} {t.source_url!r}")
            continue
        if is_medical(" ".join((t.name, t.how_to, t.hebrew_example))):
            dropped["medical"] += 1
            _log(f"dropped (medical): {t.name!r}")
            continue
        if len(kept) >= MAX_TECHNIQUES:
            dropped["over_limit"] += 1
            continue
        kept.append({"name": t.name.strip(), "how_to": t.how_to.strip(), "hebrew_example": t.hebrew_example.strip(),
                     "source_url": url, "source_title": returned[url].get("title", ""),
                     "source_trusted": is_trusted_domain(url)})
    return kept, dropped


def research_technique(
    store: SessionStore,
    client,
    settings: Settings,
    pid: str,
    question: str,
    *,
    personal: set[str],
    now: dt.datetime | None = None,
    generate_fn=generate,
    search_fn: Callable[..., list[dict]] = web_search,
) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    q = normalize_question(question)
    try:
        leaked = personal_terms_in(q, personal)
        if not q or leaked or has_hebrew(q):
            _log(f"rejected question (personal details or Hebrew): {leaked}")
            return {"status": "rejected", "message": "Rewrite it as a short, generic clinical question in "
                    "English, without names, places or other personal details."}

        nid = note_id(q)
        cached = store.get_technique_note(pid, nid)
        created = (cached or {}).get("created_at")
        if cached and created and now - created < dt.timedelta(days=settings.research_cache_days):
            _log(f"cache hit {nid}")
            return _public(cached, "cached")

        month, day = now.strftime("%Y-%m"), now.date().isoformat()
        if not settings.tavily_api_key or store.searches_in_month(month) >= settings.research_monthly_limit:
            return {"status": "unavailable", "message": "Research is not available right now; plan without it."}
        if store.research_runs_on(pid, day) >= settings.research_daily_limit:
            return {"status": "budget", "message": "Today's research budget is used up; plan without it."}
        store.add_research_run(pid, day)

        returned: dict[str, dict] = {}  # url -> result, from THIS run only
        state = {"searches": 0, "open_used": False, "unavailable": False, "queries": []}

        def handle_search(args: dict) -> dict:
            query = " ".join(str(args.get("query", "")).split())[:200]
            scope = str(args.get("scope") or "trusted")
            if state["unavailable"]:
                raise ValueError("search is unavailable now; finish with what you have")
            if state["searches"] >= settings.research_max_searches:
                raise ValueError(f"search limit reached ({settings.research_max_searches}); finish now")
            if scope not in SCOPES:
                raise ValueError(f"scope must be one of {list(SCOPES)}")
            if scope == "open" and state["open_used"]:
                raise ValueError("only one open search per run; use scope 'trusted'")
            if not query:
                raise ValueError("empty query")
            if has_hebrew(query) or personal_terms_in(query, personal):
                raise ValueError("the query contains personal details or Hebrew; use generic English keywords")
            if store.searches_in_month(month) >= settings.research_monthly_limit:
                state["unavailable"] = True
                raise ValueError("monthly search limit reached; finish with what you have")
            state["searches"] += 1
            state["open_used"] |= scope == "open"
            state["queries"].append({"query": query, "scope": scope})
            store.add_search(month)
            try:
                found = search_fn(settings.tavily_api_key, query, scope=scope)
            except TavilyUnavailable as exc:
                state["unavailable"] = True
                _log(f"tavily unavailable: {exc}")
                raise ValueError("search is unavailable now; finish with what you have") from exc
            for r in found:
                returned.setdefault(r["url"], r)
            return {"results": [{"title": r["title"], "url": r["url"], "content": r["content"]} for r in found]}

        search_tool = Tool(
            name="web_search",
            description="Search the web (Tavily). Returns up to 5 results: title, url, content snippet.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "3-6 English keywords, no personal details."},
                    "scope": {"type": "string", "enum": list(SCOPES),
                              "description": "'trusted' = professional sources only (default); 'open' = whole web, once."},
                },
                "required": ["query"],
            },
            handler=handle_search,
        )
        prompt = load_prompt()
        models = _models(settings)
        run_tool_loop(client, models, prompt["search_phase"], f"QUESTION: {q}", [search_tool],
                      max_rounds=settings.research_max_searches + 2, generate_fn=generate_fn)
        if not returned:
            status = "unavailable" if state["unavailable"] else "no_findings"
            return {"status": status, "message": "No search results; plan without research."}

        listing = "\n\n".join(
            f"[{i}] {r['title']}\nurl: {url}\nsource: {'professional (trusted)' if r['trusted'] else 'general web'}\n{r['content']}"
            for i, (url, r) in enumerate(returned.items(), 1)
        )
        result = generate_fn(client, models, f"QUESTION: {q}\n\nSEARCH RESULTS:\n{listing}",
                             types.GenerateContentConfig(system_instruction=prompt["findings_phase"],
                                                         response_mime_type="application/json",
                                                         response_schema=ResearchFindings, temperature=0.2))
        findings = result.response.parsed
        if not isinstance(findings, ResearchFindings):
            findings = ResearchFindings.model_validate_json(result.response.text)
        techniques, dropped = verify_findings(findings, returned)
        note = {
            "question": q, "summary": _strip_medical_sentences(findings.summary)[:1000],
            "techniques": techniques, "confidence": findings.confidence.value,
            "queries": state["queries"], "sources": list(returned), "dropped": dropped,
            "model": result.model, "prompt_version": str(prompt.get("prompt_version")),
        }
        if not techniques:
            _log(f"no usable techniques for {q!r} (dropped {dropped})")
            return {**_public(note, "no_findings"), "message": "Nothing reliable found; plan without research."}
        store.save_technique_note(pid, nid, note)
        _log(f"{len(techniques)} techniques from {state['searches']} searches (dropped {dropped}; model {result.model})")
        return _public(note, "ok")
    except Exception as exc:  # noqa: BLE001 -- research is optional; the plan is built anyway
        _log(f"FAILED {type(exc).__name__}: {exc!s:.300}")
        return {"status": "failed", "message": "Research failed; plan without it."}
