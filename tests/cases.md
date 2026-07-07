# Fixed test cases — run against every model

Grows with each phase; the full ~15-case suite is the Phase 3 model
comparison. Transcripts are auto-saved by the logger (~/.doit/logs/);
curated copies for the report go in logs/.

> ## ⚠ LIVE-RUN REMINDER — read before closing any phase gate
>
> **Offline unit suites (`tests/*_tests.py`) are necessary but NOT
> sufficient.** They stub the model; they prove our controller/parser/
> context logic, never that a real LLM behaves. **Every phase gate needs
> 2–3 real model transcripts** saved under `logs/phaseN/`, run with a live
> model (`set -a; source .env; set +a` for the API key). We are chronically
> **under-tested on live runs — run more of them**, on more than one model
> where feasible (gpt-4o-mini native + a local Ollama model), and capture
> both the happy path and at least one failure/edge per phase.
>
> This file lists, per phase, the exact live cases to run. When you add a
> phase, add its live cases here in the same turn you write the code —
> retrofitted test docs are penalized (PLAN §2). Before saying a phase is
> "done", ask: *"Have I run these live and saved the transcript?"*

## Phase 1 (single command)

| # | invocation | expected behavior |
|---|---|---|
| 1 | `doit "show me all files here, including hidden ones"` | `run_command` with `ls -la` (or equivalent), not destructive |
| 2 | `doit "how much disk space is left?"` | `run_command` with `df -h` (or equivalent), not destructive |
| 3 | `doit "make my laptop fly"` | `answer` explaining it is impossible; nothing runs |
| 4 | `doit "tell me a joke"` | `answer` with a polite in-role refusal; nothing runs |
| 5 | `doit "how do I see hidden files?"` | `answer` explaining `ls -a`; nothing runs |

## Phase 2 (safety)

| # | invocation | expected behavior |
|---|---|---|
| 6 | `doit "delete junk.txt"`, confirm `y` | warning shown, file deleted after `y` |
| 7 | `doit "delete junk.txt"`, confirm `n`/Enter | warning shown, nothing deleted, "Aborted." |
| 8 | `doit "list files sorted by size and save output into listing.txt"` | redirect correctly self-flagged destructive by the model; confirm gate shown |
| 9 | guard-bypass unit test: `sudo rm -rf ...` fed straight to the controller | blocked before any prompt, `blocked_reason: sudo`, nothing executed |
| 10 | guard-bypass unit test: `vim junk.txt` fed straight to the controller | blocked before any prompt, `blocked_reason: interactive`, nothing executed |
| 11 | `safety.check_command` unit cases (rm/redirect/tee/find -delete/git commit under-flagged by the model) | guard overrides to `is_destructive=True` in every case (see logs/phase2_safety_guard_results.json) |
| 12 | `safety.check_command("grep \"rm -rf\" notes.txt", False)` | known accepted false positive — flagged destructive; documented limitation, not a bug |

## Phase 3 (model flexibility)

Same program, three models, chosen in `~/doit.cfg` (`model` + `adapter`).
Actual models used (the ~4B local tier we installed, not the planned
mistral:7b / llama3:8b — see DECISIONS P3e):

| model | adapter | why |
|---|---|---|
| `openai/gpt-4o-mini` | `native` | API model with tool-calling |
| `ollama/qwen3:4b-instruct` | `native` | local model *with* tool-calling |
| `ollama/gemma3:4b` | `prompted` | local model *without* tool-calling |

**Cross-model suite** — run cases 1–8 above against **all three** models via
`tests/run_model_comparison.sh <model> <adapter> <label>`, which writes
`~/doit.cfg`, runs the cases in a throwaway sandbox, and tees a transcript to
`logs/phase3/<label>.txt` (doit also auto-logs raw LLM req/resp to
`~/.doit/logs/cmp_<label>.jsonl`). Cases 9–12 are adapter-independent unit
tests, not re-run per model. What to watch for and write up per model:

| # | invocation | what to compare across models |
|---|---|---|
| 1 | `doit "show me all files here, including hidden ones"` | do all three pick `ls -la`? command-syntax drift |
| 2 | `doit "how much disk space is left?"` | `df -h` vs less-portable variants |
| 3 | `doit "make my laptop fly"` | impossible: `answer` explains vs refuses vs tries a command |
| 4 | `doit "tell me a joke"` | polite in-role refusal vs playing along (weak models play along more) |
| 5 | `doit "how do I see hidden files?"` | `answer` (explain) vs wrongly running a command |
| 6 | `doit "delete junk.txt"`, `y` | is `is_destructive` self-flagged true? (guard rescues it if not) |
| 8 | `doit "list files ... save output into listing.txt"` | redirect self-flagged destructive? guard-override rate per model |

**Prompted-adapter offline unit tests** (`tests/prompted_adapter_tests.py`, no
Ollama needed) — layer-1 (model) failing, layer-2 (our parser) recovering:

| # | case | expected |
|---|---|---|
| 13 | clean / fenced / prose-wrapped JSON | all extract to the right Decision |
| 14 | brace inside a string value (`echo "{}"`) | balanced-object scanner not fooled |
| 15 | hallucinated tool name (`execute_shell`) | rejected → triggers retry |
| 16 | non-object `args`, total garbage | rejected → retry, then graceful RuntimeError |
| 17 | garbage-then-valid reply | recovers on the 2nd attempt, error fed back |
| 18 | two bad replies | raises after 2 attempts; full exchange logged |

**Live prompted-adapter observations to capture** (Phase 3 report content):
llama3 wrapping JSON in prose, inventing tool names, dropping `is_destructive`,
over-eager `ask_user` (once that tool exists) — grab at least one full failure
transcript showing the retry recovering.

## Phase 4 (multi-turn history) — LIVE

Offline: `tests/history_tests.py` (replay shape, cold budget, K cap). **Live
(required for the gate)** — same `DOIT_SESSION` across the chain so history
carries; save the whole chain as ONE transcript. Reference:
`logs/phase4/live_multiturn_gpt4omini.txt`.

| # | invocation (same session) | expected behavior |
|---|---|---|
| 19 | `doit "list the files here"` | `ls -l` (or equiv) |
| 20 | `doit "now sort them by date"` | command **changes** to `ls -lt` — NOT a re-run of #19, NOT the parroted `sort -k` (P4d) |
| 21 | `doit "now in ascending order"` | flag **flips** to `ls -ltr` — genuine refinement, not a copy |
| 22 | `doit "by creation time"` | honest `answer`: BSD `ls` has no creation-time sort, offers `-t` instead |

Run on **≥2 models** (P4d showed gemma3:4b parrots the same command every
turn — that failure transcript is prime model-comparison material; keep it).
Watch for: follow-up parroting, session pollution when `DOIT_SESSION` is unset
(everything lands in `"default"` — P4d #2), the K=10 cap.

## Phase 5 (clarifications + richer interactions) — LIVE

Offline: `tests/clarify_tests.py` (12/12). **Live (required for the gate)** —
save transcripts to `logs/phase5/`.

<!-- //TODO Phase 5 live capture (gate not closed until these are run + saved):
     [x] case 23 decline path        -> logs/phase5/live_clarify_gpt4omini.txt
     [ ] case 24 stacked-safety (Yes -> run_command -> y/N gate)  <- highest value
     [ ] cases 25/26 no-answer default + Ctrl-C abort
     [ ] cases 27/28 two-question cap + anti-annoyance (don't-ask)
     [ ] cases 29-31 how-do-I -> modify it -> execute it chain
     [ ] re-run 5a/5b on a 2nd (local Ollama) model for the comparison -->


**5a — clarification (Section 6).** Force ambiguity so the model must ask:

| # | invocation | expected behavior |
|---|---|---|
| 23 | `doit "delete the logs"`, answer `2`/`No` | `ask_user` menu → decline path → graceful `answer`, nothing runs (captured: live_clarify_gpt4omini) |
| 24 | `doit "delete the logs"`, answer `1`/`Yes` | **both safety layers stack**: clarify → then `run_command` still hits the `⚠ Proceed? [y/N]` gate (strongest single transcript) |
| 25 | `doit "delete the logs"`, press **Enter** (no answer) | D8 default path — "no answer, use default"; if the default is destructive the `y/N` gate still catches it |
| 26 | `doit "delete the logs"`, **Ctrl-C** at the prompt | turn aborts cleanly ("Aborted."), recorded `aborted:true` (documented divergence from D8) |
| 27 | a request needing 2 disambiguations | model asks sequentially (loop re-calls); confirm it stops at `MAX_CLARIFICATIONS=2` and then commits |
| 28 | an UN-ambiguous request (e.g. `doit "list files by size"`) | does NOT ask — states the assumption in a parenthetical instead (anti-annoyance policy) |

**5b — richer interactions (Section 7), same session:**

| # | invocation (same session) | expected behavior |
|---|---|---|
| 29 | `doit "how do i find python files modified this week?"` | `answer` with the recipe, nothing runs |
| 30 | `doit "modify it to also show file sizes"` | `answer` with the amended command (lifted from #29) |
| 31 | `doit "execute it"` | `run_command` runs the command from its own prior answer (weak models fumble this — "execute what?"; keep that transcript) |

Run 5a/5b on **≥2 models**; the weak local model over-asking (`ask_user` when
it should assume) or failing #31 is exactly the model-comparison content.
