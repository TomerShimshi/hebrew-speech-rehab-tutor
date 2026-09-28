# Sub-plan 07: Web-search sub-agent

Part of the [master design](00-master-design.md). Depends on [06](06-games-integration.md).

## Goal
Calls #1 and #3 can look up evidence-based therapy advice on the web. Google Search grounding is only free on `gemini-2.5-flash` (500 requests/day), and grounding can't be combined with function calling in the same request. So search runs as a **separate sub-agent call** with its own system prompt.

## Files
| File | Purpose |
|---|---|
| `prompts/search_agent.yaml` | System prompt. It casts the model as a research assistant to a speech-language pathologist and has it prefer clinical sources (ASHA, Aphasia United, AARP, PubMed/PMC, aphasiology journals, Israeli/Hebrew SLP sources). Every claim needs a source URL from the grounding metadata. Techniques must be safe for home practice and adapted to Hebrew and the given `speech_profile`. No medical, medication or prognosis advice. If nothing reliable turns up, it says "no reliable evidence found". Output is JSON `{summary, techniques[{name, how_to, hebrew_example, source_url}], confidence}`. |
| `app/agent/search_agent.py` | Calls `SEARCH_MODEL=gemini-2.5-flash` with the `google_search` tool, parses the JSON, and matches source URLs against the grounding metadata, dropping any it can't match. It passes only minimal patient context (profile type, goal, difficulty), never names. Results are cached in `technique_notes`, keyed by a normalized question. |
| `app/agent/tools.py` | Adds `search_therapy_advice(question, context)`, available in calls #1 and #3. |
| `app/config.py` | `SEARCH_MODEL`, `ENABLE_WEB_SEARCH` (default true), and a daily call budget (e.g. 20) so we stay far below the free limit. |
| `tests/` | The system prompt renders, JSON parsing and URL filtering work, cache hits skip the model, and the budget is enforced. |

## Done when
- [ ] `pytest` passes.
- [ ] A plan facing a new difficulty includes a technique with a real source link.
- [ ] Asking the same question again hits the cache.
- [ ] Turning off `ENABLE_WEB_SEARCH` falls back to `get_therapy_technique`.

## Commit
`Sub-plan 07: grounded web-search sub-agent for therapy advice`
