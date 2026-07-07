# Fixed test cases — run against every model

Grows with each phase; the full ~15-case suite is the Phase 3 model
comparison. Transcripts are auto-saved by the logger (~/.doit/logs/);
curated copies for the report go in logs/.

## Phase 1 (single command)

| # | invocation | expected behavior |
|---|---|---|
| 1 | `doit "show me all files here, including hidden ones"` | `run_command` with `ls -la` (or equivalent), not destructive |
| 2 | `doit "how much disk space is left?"` | `run_command` with `df -h` (or equivalent), not destructive |
| 3 | `doit "make my laptop fly"` | `answer` explaining it is impossible; nothing runs |
| 4 | `doit "tell me a joke"` | `answer` with a polite in-role refusal; nothing runs |
| 5 | `doit "how do I see hidden files?"` | `answer` explaining `ls -a`; nothing runs |
