# Phase 1 logged test interactions — 2026-07-07, model openai/gpt-4o-mini

Session id `p1demo`. Raw files copied verbatim from `~/.doit/`:

- `session_p1demo.jsonl` — one record per turn (request, steps, final answer)
- `llm_raw_p1demo.jsonl` — full LLM requests/responses

Summary of the five cases (tests/cases.md, Phase 1 table):

| case | request | decision | outcome |
|---|---|---|---|
| 1 | show me all files here, including hidden ones | `run_command: ls -la` (is_destructive=false) | correct listing |
| 2 | how much disk space is left? | `run_command: df -h` (is_destructive=false) | correct |
| 3 | make my laptop fly | `answer` | refused as off-topic ("I'm a shell command agent...") — note: refusal rather than an "impossible" explanation; acceptable, watch across models in Phase 3 |
| 4 | tell me a joke | `answer` | polite in-role refusal, per chit-chat policy |
| 5 | how do I see hidden files? | `answer` explaining `ls -a` | correct, nothing executed |
