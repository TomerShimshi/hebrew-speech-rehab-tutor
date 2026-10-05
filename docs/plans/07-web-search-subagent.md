# Sub-plan 07: Research sub-agent (evidence-based therapy advice, with sources)

Part of the [master design](00-master-design.md). Depends on [05](05-next-class-builder.md)/[06](06-games-integration.md) (the plan builder).

## Goal
When the plan builder meets something its built-in techniques don't cover (a new difficulty, a stuck pattern, or a goal that hasn't moved), it can **look up evidence-based, home-practice techniques**, with **real, checkable sources**, and use them in the next lesson plan. The findings are kept, so the caregiver page (08) can show "what the research suggests and why".

## What changed since the master design (checked live 2026-10-04)
- **Google Search grounding is not available on the free tier.**
  - On our key, every current model answers `429` as soon as the `google_search` tool is on, while the same models answer normally without it.
  - The pricing page lists free-tier grounding as "Not available" for all current models.
  - `gemini-2.5-flash`, which had free grounding, now returns **404 "no longer available to new users"**.
- **Search alternatives we looked at:**
  - **Google Programmable Search / Custom Search JSON API:** closed to new customers, discontinued on 2027-01-01, and new engines are capped at 50 sites ([Google](https://developers.google.com/custom-search/v1/overview)).
  - **Brave Search API:** needs a card, and **storing** results needs a paid storage-rights plan, which conflicts with our cache.
  - **DuckDuckGo:** has no official web-search API. The free "Instant Answer" API returns encyclopedia-style snippets, not search results. Libraries that "search DuckDuckGo" scrape its website, which is against its terms, breaks without warning, and is often blocked from cloud servers. **Not used, not even as a fallback.**
  - **PubMed E-utilities + Gemini URL context:** both work for free. We built and tested them, but they meant more code and more ways to fail: PubMed needs short keyword queries, and one ASHA page returns 404 to URL context. **Dropped** (Tomer, 2026-10-04): Tavily restricted to trusted sites covers the same sources, PubMed included.
  - **Tavily:** **1,000 searches a month free, no card needed**, and it can restrict results to chosen sites. **Chosen as the only source** (Tomer, 2026-10-04).
- **When Tavily runs out, research is skipped.** The builder falls back to the curated `therapy_techniques.yaml`, exactly as it works today. Research is an extra; a lesson never depends on it.

## Out of scope
- Showing research findings in a UI (08). Until then they're visible in Firestore and the debug prompt files.
- Any medical, medication, device or stimulation advice. Excluded by design (see guardrails).
- Any fallback search engine. If Tavily is unavailable, there is no research that month.

## Design decisions
- **When research happens: the planner decides, within limits.**
  - The plan builder (call #3) becomes **two phases**, like the memory update:
    1. an optional **tool phase** with one tool, `research_technique(question)`
    2. the existing structured plan output
  - Guidance: research only when one of these applies:
    - the memory shows a difficulty the curated `therapy_techniques.yaml` doesn't address
    - a goal has made no progress over several sessions (from `probe_results` and the word bank)
    - the therapist's notes name something new
  - Otherwise the builder works exactly as today.
- **The research sub-agent** (`app/agent/research.py`) is its own small tool loop (the existing `runner.py`, at most 4 rounds) with its own system prompt (`prompts/research_agent.yaml`).
- **Its one tool is `web_search(query, scope)`.** Our code calls the Tavily API (basic search, 5 results: title, URL, content snippet).
  - **`scope: "trusted"` (the default)** limits results to the trusted sites in `prompts/trusted_sources.yaml`. Tavily's `include_domains` does the filtering. The sites:
    - `asha.org` (the American Speech-Language-Hearing Association)
    - `pubmed.ncbi.nlm.nih.gov` and `ncbi.nlm.nih.gov` (PubMed, PMC, StatPearls)
    - `nidcd.nih.gov`
    - `aphasiatrials.org` (Aphasia United)
    - `aphasiapathway.com.au` (the Australian aphasia guidelines)
  - **`scope: "open"`** searches any site, e.g. for Hebrew resources or practical home-practice guides. Each research run may do it **at most once**. Its results are marked `trusted: false`, and the prompt prefers clinical and professional sources (universities, health systems, professional associations).
  - The prompt asks for short English keyword queries (3–6 words, e.g. "semantic feature analysis home practice").
- **Output:** structured JSON `{summary, techniques[{name, how_to, hebrew_example, source_url, source_trusted}], confidence}`. If nothing reliable is found, the agent must say so (empty `techniques`) rather than guess.
- **Usage limits, kept well under Tavily's free 1,000 a month:**
  - **Per research run:** at most **3 searches** (counted by our code; a 4th call returns an error to the model).
  - **Per plan:** at most **1 research run**.
  - **Per day:** at most **3 research runs** per account.
  - **Per month:** our own **app-wide counter stops at 800 searches** (`RESEARCH_MONTHLY_LIMIT`), before Tavily's limit.
  - **No key or limit reached:** with no `TAVILY_API_KEY`, the monthly limit reached, or a Tavily usage-limit / auth error, the `research_technique` tool is not offered (or returns "research unavailable"). The plan is built without it.
  - **Expected use:** a few dozen searches a month, thanks to the cache below.
- **Guardrails, enforced by code, not just by the prompt:**
  - **Sources must be real.** A technique is kept only if its `source_url` is a URL that `web_search` returned **in this run**. Anything else is dropped as a possible hallucination. `source_trusted` is set by our code from the URL's domain, never by the model.
  - **Behavioral home practice only.** A blocklist filter drops any technique matching it, even if the model included it. It covers tDCS, TMS, transcranial, stimulation, medication, drug, pharmacological, thrombolytics, surgery, device, injection, botox and the Hebrew equivalents. The prompt says the same.
  - **No personal data leaves the app.**
    - The question sent to research is written by the builder as a **generic clinical question**, e.g. "mild anomia for proper names in a fluent speaker; retrieval practice at home".
    - Before any Tavily call, the code checks the question and **every search query** for his names and places from the memory and profile, and rejects any query that contains one.
    - Tavily only ever sees generic keywords.
- **Caching:** results are saved in `patients/{email}/technique_notes/{id}`, keyed by a normalized question, and reused for 30 days without searching. The builder sees the latest notes in its context even when it doesn't search.
- **How it reaches the tutor:** only through the plan. The builder may turn a found technique into the session's activity or practice items. The tutor never sees sources and never cites studies to Dad.
- **Later (after the POC):** once billing is on the Gemini key, Gemini's own Google Search grounding could replace or complement Tavily behind the same `web_search` tool, with the same guardrails.

## Files
| File | Purpose |
|---|---|
| `app/research_sources.py` | `web_search()` (Tavily REST, basic depth, 5 results, `trusted`/`open` scope), plus the guardrail helpers: the trusted-domain check, the medical blocklist and the personal-term check. The PubMed and URL-context code written earlier is removed. |
| `app/agent/research.py` | The sub-agent: a tool loop with `web_search` → structured findings → source verification + blocklist → cache. Counts searches per run. Never raises. |
| `prompts/research_agent.yaml`, `prompts/trusted_sources.yaml` | The sub-agent's system prompt; the trusted domains (now only a domain list, no page URLs). |
| `app/agent/next_class.py` + `prompts/next_class.yaml` | Becomes two phases: an optional tool phase with `research_technique`, then the plan. Gets recent technique notes as context. Daily budget. |
| `app/store.py` | `get_technique_note`, `save_technique_note`, `recent_technique_notes`; the per-account daily research counter and the app-wide monthly search counter. |
| `app/config.py`, `deploy/*.sh`, `.env.example` | `TAVILY_API_KEY` (Secret Manager, from `.env`), `RESEARCH_DAILY_LIMIT=3`, `RESEARCH_MONTHLY_LIMIT=800`. |
| `tests/` | With a fake Tavily (no real calls): `trusted` scope sends the domain list; only one `open` search per run; at most 3 searches per run; fake source URLs dropped; medical techniques (tDCS) dropped; personal-data rejection; cache hit; daily and monthly limits; Tavily usage-limit error → research skipped; the builder still works when research fails, is skipped or has no key. |

## Tasks
1. [x] Cut `research_sources.py` down to Tavily + guardrail helpers, and `trusted_sources.yaml` down to domains; tests; a **live Tavily check** (one trusted and one open search).
2. [x] The research sub-agent + guardrails + cache + limits, with tests; a **live dry run** on a real question, showing the findings and their sources for review.
3. [x] The builder's tool phase + notes in context; a dry run on Tomer's memory.
4. [x] Deploy (the `TAVILY_API_KEY` secret), then a real session. Tomer's session (2026-10-05): the builder chose **not** to research and saved a valid reason (name retrieval is covered by the curated techniques). This is the intended behaviour: it doesn't overuse search. The research path itself was verified in the live dry run (task 2).
5. [x] Commit and push.

## Notes from building it
- **Tavily's basic search already returns ~2,700 characters per result** (1 credit). The first dry run cut them to 1,200 and found nothing usable; 3,000 works. The same ASHA article often comes back twice (`/doi/abs/` and `/doi/`), so duplicates (same title or same opening text) are dropped.
- **The findings prompt was too strict at first** ("no pictures, no therapist"). Now: the source must *support* the technique, and the agent adapts it to a voice-only session. The Hebrew examples must be natural and grammatical (she: feminine, him: masculine).
- **Personal-data check:** queries with any Hebrew letters are rejected (his names and places are usually stored in Hebrew), plus capitalized mid-sentence words from his memory and profile ("his wife Rina", "lived in Haifa") and the account / games profile names.
- **The builder may decide not to research.** Its one-line reason is saved on the plan (`research.reason`), next to the question, status and technique names.
- **Tests never use the real key:** `Settings()` also reads the developer's `.env`, so `conftest.py` blanks `TAVILY_API_KEY` before anything is created.
- **Plan guard (added with 07):** the smallest fallback model ignored the rules: it used Jerusalem and Tel Aviv as new check-in items and used the same 3 names for practice. The code now drops too-famous NEW check-in items and practice items that repeat a check-in item, and rejects the plan (the hourly sweep rebuilds it) if fewer than 3 check-in items remain or every practice item was a repeat.
- **Secret Manager:** 5 active versions (free up to 6); `patient-profile` is a leftover from before the profile moved to the bucket.

## Manual steps for Tomer
- Create a free **Tavily** account at https://app.tavily.com (no card needed), copy the API key, and put `TAVILY_API_KEY=...` in `.env` (and save). `setup_gcp.sh` moves it into Secret Manager.
- Review the first research results (task 2): are the techniques sensible, home-safe, and at Dad's level?
- Optional: suggest trusted sites to add (e.g. Israeli or Hebrew speech-therapy sources his therapist uses).

## Done when
- [x] `pytest` passes.
- [x] A live research run returns 2–3 home-practice techniques, each with a real URL that the search returned, mostly from trusted sites, and nothing medical.
- [x] Fabricated sources and medical techniques are dropped by code (tests).
- [x] No personal names or places are ever sent to Tavily (tests).
- [x] Research stays within the per-run, daily and monthly limits, and a research failure or an exhausted Tavily quota never stops a plan from being built (tests).

## Commit
`Sub-plan 07: research sub-agent (Tavily, trusted sites) with source verification`
