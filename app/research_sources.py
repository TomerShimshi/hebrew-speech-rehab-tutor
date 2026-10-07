"""The research sub-agent's search (sub-plan 07; fallback added in 10), as plain functions.

  web_search(api_key, query, scope)   Tavily -- the first choice (free 1,000 / month)
                                      scope "trusted": only the sites in trusted_sources.yaml
                                      scope "open":    any site (results marked trusted=False)
  gemini_search(client, models, ...)  Gemini + Google Search grounding -- the fallback when
                                      Tavily is unavailable (paid tier: 5,000 / month included)

It returns plain dicts and raises on failure (TavilyUnavailable when the key or the monthly
quota is the problem -- then research is skipped). Guardrails that don't depend on the model
live here too: the trusted-domain check, the medical blocklist and the personal-data check.
"""

import json
import re
import urllib.error
import urllib.request
from functools import lru_cache
from urllib.parse import urlsplit

import yaml
from google.genai import types

from app.config import REPO_ROOT

TRUSTED_PATH = REPO_ROOT / "prompts" / "trusted_sources.yaml"
TAVILY_URL = "https://api.tavily.com/search"
TIMEOUT_S = 20
CONTENT_CHARS = 3000  # basic search already returns ~2,700 chars of each page
SCOPES = ("trusted", "open")

# Never suggested to Dad, whatever the source says: only behavioral home practice is in scope.
MEDICAL_BLOCKLIST = re.compile(
    r"\b(tdcs|tms|rtms|transcranial|stimulation|neuromodulation|medication|medicine|drug|"
    r"pharmac\w*|dose|dosage|surgery|surgical|implant|device|injection|botox|thromboly\w*|"
    r"תרופ\w*|גירוי מוחי)\b",
    re.IGNORECASE,
)


class TavilyUnavailable(Exception):
    """Bad/missing key or quota used up: stop researching (not worth retrying)."""


@lru_cache
def trusted_domains() -> tuple[str, ...]:
    data = yaml.safe_load(TRUSTED_PATH.read_text(encoding="utf-8"))
    return tuple(d.lower() for d in data["trusted_domains"])


def is_trusted_domain(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in trusted_domains())


HEBREW = re.compile(r"[\u0590-\u05FF]")


def has_hebrew(text: str) -> bool:
    """Research queries are English keywords; Hebrew in one usually means a name or place of his."""
    return bool(HEBREW.search(text or ""))


def is_medical(text: str) -> bool:
    return bool(MEDICAL_BLOCKLIST.search(text or ""))


def personal_terms_in(text: str, personal_terms: set[str]) -> list[str]:
    """His names/places (from the memory) found in an outgoing query -- those must never leave."""
    return sorted(t for t in personal_terms
                  if len(t) >= 3 and re.search(rf"(?<!\w){re.escape(t)}(?!\w)", text or "", re.IGNORECASE))


def _post_json(url: str, body: dict, api_key: str) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read())


def web_search(api_key: str, query: str, scope: str = "trusted", max_results: int = 5) -> list[dict]:
    if not api_key:
        raise TavilyUnavailable("no TAVILY_API_KEY")
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}")
    body = {"query": query, "search_depth": "basic", "max_results": max_results, "include_answer": False}
    if scope == "trusted":
        body["include_domains"] = list(trusted_domains())
    try:
        data = _post_json(TAVILY_URL, body, api_key)
    except urllib.error.HTTPError as e:
        # 401 bad key; 432/433 plan or pay-as-you-go limit reached; 429 rate limit
        if e.code in (401, 403, 429, 432, 433):
            raise TavilyUnavailable(f"tavily HTTP {e.code}") from e
        raise
    results, seen = [], set()
    for r in data.get("results", []):
        title = (r.get("title") or "").strip()
        content = (r.get("content") or "")
        keys = {title.lower(), " ".join(content[:300].lower().split())} - {""}
        if keys & seen:  # the same article under two URLs (e.g. /doi/abs/ and /doi/)
            continue
        seen |= keys
        results.append({"title": title, "url": r.get("url", ""),
                        "content": content[:CONTENT_CHARS],
                        "trusted": is_trusted_domain(r.get("url", ""))})
    return results


# ---- Gemini + Google Search: the fallback (10) ---------------------------------------------------

class SearchUnavailable(Exception):
    """The fallback can't search either (e.g. 429 on the free tier, every model failing)."""


REDIRECT_HOST = "grounding-api-redirect"


def resolve_url(uri: str, timeout_s: float = 6) -> str:
    """Grounding sources are Google redirect links; follow one to the real page address."""
    if REDIRECT_HOST not in (uri or ""):
        return uri
    headers = {"User-Agent": "Mozilla/5.0 (research link check)"}
    for method in ("HEAD", "GET"):  # some redirects only answer a normal GET
        try:
            req = urllib.request.Request(uri, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                if REDIRECT_HOST not in resp.geturl():
                    return resp.geturl()
        except urllib.error.HTTPError as exc:  # the page itself may refuse us -- its address is still known
            if exc.url and REDIRECT_HOST not in exc.url:
                return exc.url
        except Exception:  # noqa: BLE001
            pass
    return uri  # unresolved: kept, but it can't count as trusted by its URL


def gemini_search(client, models, query: str, scope: str = "trusted", *, generate_fn,
                  resolve=resolve_url, max_results: int = 5) -> list[dict]:
    """One grounded Gemini call; the sources come from its grounding metadata (never from its
    own text), each resolved to its real address. A "trusted" search keeps only trusted sites."""
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}")
    sites = ", ".join(trusted_domains())
    ask = (f"Search the web for: {query}\n"
           + (f"Use only pages from these sites: {sites}.\n" if scope == "trusted" else "")
           + "Then summarize in 3-5 sentences what the sources say, for a speech-language pathologist.")
    try:
        result = generate_fn(client, models, ask, types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())], temperature=0.2))
    except Exception as exc:  # noqa: BLE001 -- e.g. 429 on the free tier
        raise SearchUnavailable(f"gemini search: {exc!s:.150}") from exc
    candidate = (result.response.candidates or [None])[0]
    meta = getattr(candidate, "grounding_metadata", None)
    chunks = list(getattr(meta, "grounding_chunks", None) or [])
    snippets: dict[int, list[str]] = {}
    for support in getattr(meta, "grounding_supports", None) or []:
        text = getattr(getattr(support, "segment", None), "text", "") or ""
        for i in getattr(support, "grounding_chunk_indices", None) or []:
            snippets.setdefault(i, []).append(text)
    summary = (result.response.text or "")[:CONTENT_CHARS]
    results, seen = [], set()
    for i, chunk in enumerate(chunks):
        web = getattr(chunk, "web", None)
        if not web or not getattr(web, "uri", None):
            continue
        url = resolve(web.uri)
        title = (getattr(web, "title", "") or "").strip()
        if url in seen:
            continue
        seen.add(url)
        # The title of a grounding source is usually its domain ("asha.org"): a fallback when
        # the redirect couldn't be resolved.
        trusted = is_trusted_domain(url) or (REDIRECT_HOST in url and bool(title) and is_trusted_domain(f"https://{title}/"))
        content = " ".join(snippets.get(i, [])) or summary
        results.append({"title": title, "url": url, "content": content[:CONTENT_CHARS], "trusted": trusted})
    if scope == "trusted":
        results = [r for r in results if r["trusted"]]
    return results[:max_results]
