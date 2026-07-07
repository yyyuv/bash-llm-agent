# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

This is a **university assignment (Assignment 3: Agents — an agentic shell tool called `doit`)**. Plans: [PLAN.md](PLAN.md) (compact reference) and [PLAN_DETAILED.md](PLAN_DETAILED.md) (rationale).

**Phases 0–5 complete** (2026-07-07): `doit` entry point (executable, symlinked into `~/.local/bin`), `doitlib/` (config, state, llm with **both** the native and prompted adapters, context, tools `run_command`+`answer`, controller with `max_steps=1`, safety), prompt templates in `prompts/`, [acdl/v1_single.acdl](acdl/v1_single.acdl) + [acdl/v2_safety.acdl](acdl/v2_safety.acdl) + [acdl/v3_prompted.acdl](acdl/v3_prompted.acdl), logged test interactions in [logs/phase1/](logs/phase1/), [logs/phase2/](logs/phase2/), [logs/phase3/](logs/phase3/) (all native-model runs passing on `openai/gpt-4o-mini`).

Phase 2 adds [doitlib/safety.py](doitlib/safety.py): a deterministic regex guard that overrides the model's `is_destructive` self-report, hard-refuses `sudo` and interactive/full-screen programs (vim, less, bare ssh, bare python, ...) with no prompt at all, and gates genuinely destructive-but-legal commands behind a `y`/`N` confirmation in `controller._handle_run_command`. Abort is recorded in session history for a future turn's "actually yes" (Phase 4). Known accepted limitations (documented in DECISIONS.md P2c/P2d): `ssh -p 2222 host` (flag-with-value) is misread as a non-interactive command, and `grep "rm -rf" notes.txt` false-positives as destructive — both intentional tradeoffs of the regex approach, not bugs.

Phase 3 adds the **prompted adapter** (model flexibility): [doitlib/llm.py](doitlib/llm.py) now dispatches on `config.adapter` (`native` | `prompted`) behind one `call()` → `Decision`. The prompted adapter (for local models without tool-calling, e.g. `ollama/llama3:8b`) renders `TOOL_SCHEMAS` into the system prompt ([prompts/prompted_suffix.txt](prompts/prompted_suffix.txt)), asks for bare JSON, and extracts/validates it (`_extract_json_object` = de-fence + string-aware balanced-brace scan, then validate tool name + args), retrying once with the parse error fed back ([prompts/prompted_retry.txt](prompts/prompted_retry.txt)) before raising. `controller._append_tool_result` branches on `tool_call_id is None` to feed results back as a `U:` user message (prompted) vs the native `T:` tool role — the v2↔v3 ACDL diff. Offline unit tests [tests/prompted_adapter_tests.py](tests/prompted_adapter_tests.py) (10/10, results in [logs/phase3/](logs/phase3/)) prove parse/validate/retry against the exact malformed replies weak models emit — run them with `/usr/bin/python3` (the interpreter that has litellm). See DECISIONS.md P3a–P3d.

**Phase 3 gate: closed.** The live three-model comparison is done — Ollama is installed (`/opt/homebrew/bin/ollama`) and the planned mistral:7b / llama3:8b were swapped for `qwen3:4b-instruct` (native) + `gemma3:4b` (prompted) (DECISIONS.md P3e). Curated transcripts live in [logs/phase3/](logs/phase3/): `gpt4omini_native`, `gpt4omini_prompted`, `qwen3_native`, `qwen3_prompted`, `gemma3`.

Notes: deps installed via `pip3 install --user litellm` on system Python 3.9; `OPENAI_API_KEY` lives in a gitignored `.env` at the repo root (`set -a; source .env; set +a` before running — plain `source` does not export it to the doit subprocess); `~/.local/bin` must be on PATH (added to `~/.zshrc`). Local Ollama models need no API key.

Phase 4 adds **multi-turn history**: [doitlib/state.py](doitlib/state.py) `load_recent_turns(session_id, K)` reads the session JSONL; [doitlib/context.py](doitlib/context.py) `history_messages`/`_replay_turn` replay the last `HISTORY_TURNS=10` turns as plain `U:/A:` chat messages (NOT the native `T:` tool role — cross-turn has no live `tool_call_id`; see DECISIONS.md P4a) and `build_messages(request, config, session_id)` splices them between the env block and the current request; [doitlib/tools.py](doitlib/tools.py) `truncate_for_context` gained hot/cold budgets (D7: `HOT_HEAD/TAIL=3000/1000`, `COLD_HEAD/TAIL=1000/300`), older turns using the cold budget. max_steps is unchanged (still single-command per turn; P4b). Spec [acdl/v4_history.acdl](acdl/v4_history.acdl); offline suite [tests/history_tests.py](tests/history_tests.py) (10/10, [logs/phase4/](logs/phase4/)).

Phase 4 gate is CLOSED: passing live transcript at [logs/phase4/live_multiturn_gpt4omini.txt](logs/phase4/live_multiturn_gpt4omini.txt) ("sort them by date" → `ls -lt`, "ascending" → `ls -ltr`, "by creation time" → honest answer) proves follow-up resolution end-to-end on `openai/gpt-4o-mini`. Prompt was hardened in this phase (P4d) against follow-up parroting and fragile `sort -k N`; config reverted to gpt-4o-mini native. Known open limitation (P4d #2): without the shell snippet `DOIT_SESSION` falls back to `"default"`, so all terminals share one history — isolate manually with `DOIT_SESSION=<id>` until the snippet lands (Phase 7/8).

Phase 5 adds **clarifications** (`ask_user`, PLAN_DETAILED Section 6) and **richer interactions** (Section 7). New third tool `ask_user(question, options?)` in [doitlib/tools.py](doitlib/tools.py); the [doitlib/controller.py](doitlib/controller.py) `run_turn` loop now re-enters after an `ask_user` (prints the question + numbered options via `_prompt_user`, blocks on `input()`, feeds the reply back, re-calls the LPU) — a clarification is a within-turn step, NOT a command step, so single-command mode still runs exactly one command after clarifying (P5a). Non-annoyance is enforced both in the prompt (ask only when a wrong guess is destructive or interpretations differ materially) AND structurally: `controller.MAX_CLARIFICATIONS=2` caps questions per turn (P5b). D8 (empty/EOF input) is realized via the existing safety gate — "no answer → use stated default", and if that default is destructive the `_confirm_destructive` `y`-prompt still gates it (no new check at ask time); Ctrl-C aborts the turn. Section 7 needed **zero** new code (P5c): "how do I X?" is `answer`, and "modify it"→"execute it" resolves through Phase 4 history replay. Past `ask_user` exchanges are replayed into history (P5d, [doitlib/context.py](doitlib/context.py) `_replay_turn`). Spec [acdl/v5_clarify.acdl](acdl/v5_clarify.acdl); offline suite [tests/clarify_tests.py](tests/clarify_tests.py) (12/12, [logs/phase5/](logs/phase5/)). See DECISIONS.md P5a–P5d + D8.

**Next:** capture the Phase 5 live transcripts to close the gate, then **Phases 6–9 remain ⏸-gated** (re-review before starting); Phase 6 is memory (`remember`/`forget`).

<!-- //TODO close Phase 5 gate — live transcripts still owed (checklist in tests/cases.md):
     case 23 decline path is DONE (logs/phase5/live_clarify_gpt4omini.txt).
     Still to run + save to logs/phase5/: case 24 stacked-safety (answer Yes -> run_command
     -> Phase 2 y/N gate; highest value), cases 25/26 (no-answer default + Ctrl-C abort),
     cases 27/28 (2-question cap + anti-annoyance), cases 29-31 (how-do-I -> modify -> execute),
     and a 2nd-model (local Ollama) run of 5a/5b for the comparison. -->


> **Maintenance rule:** update this "Current state" section at the end of every completed phase (what exists, what phase is next). A stale CLAUDE.md misleads future sessions.

> **Testing rule (live tests, not just offline):** offline `tests/*_tests.py` suites stub the model — they prove our code, never that a real LLM behaves. **A phase gate is NOT closed without 2–3 live model transcripts in `logs/phaseN/`** (ideally on ≥2 models: gpt-4o-mini native + a local Ollama one). We are chronically under-tested on live runs — **run more.** [tests/cases.md](tests/cases.md) documents the exact live cases per phase; add a phase's live cases there in the same turn you write its code.

**How to use the plan files:** [PLAN.md](PLAN.md) §2 is the authoritative build order — read the current phase's section before starting it. [PLAN_DETAILED.md](PLAN_DETAILED.md) is the human-oriented rationale doc; consult it only when a design question arises. Decisions marked ⏸ there are **open** — never resolve them yourself, ask the user.

The deliverable is `doit`: you type an English request in your terminal; it decides which shell command(s) to run and runs them. Grading rewards the harder "agentic" parts (memory, user shell-history awareness, multi-terminal sessions, an extension) **and** ACDL documentation written *as you go* — retrofitted docs are explicitly penalized.

## The one non-negotiable architectural principle

`doit` is a **Controller wrapping an LPU** (LLM). The LLM only ever sees text and emits a *structured decision* (tool name + args); it never acts. The Python Controller owns the loop, all state, tool execution, and safety. Keep this separation strict — every feature is either a **tool**, a piece of **context**, or **controller logic**, nothing else. Violating it forces rewrites later.

## Core design (locked decisions)

**Five tools only** — the tool set *is* the decision schema, the single contract all models code against. Do NOT add a tool per shell command (`ls`/`grep`/`git`); the shell string in `run_command` is the universal tool.

| tool | args | purpose |
|---|---|---|
| `run_command` | `command, is_destructive, explanation` | translate & execute; `is_destructive` flag is layer 1 of safety |
| `answer` | `text` | talk without executing; also the **finish** signal that ends the loop |
| `ask_user` | `question, options[]` | clarification, resolved *within the same invocation* (a loop iteration, not a new `doit` call) |
| `remember` / `forget` | `fact` / `id` | persistent memory |
| `change_dir` | `path` | special-cased `cd` (see below) |

Multiple tool calls may occur in one turn (e.g. `change_dir` then `remember`).

**The `cd` trap** — a Python subprocess *cannot* change the parent shell's cwd. Solution: `change_dir` validates the path and writes it to `~/.doit/cd_target_$DOIT_SESSION`; a shell **function wrapper** (installed via the bashrc/zshrc snippet) reads that note after `doit` exits and performs the real `cd` inside the shell. Also record new cwd in session state. This is the most-likely-to-bite mechanism — understand it before touching `change_dir` or the shell snippets.

**Two-layer safety** (defense in depth): (1) the model self-reports `is_destructive` + `explanation` in the same JSON; (2) a deterministic Python regex guard *overrides* the model when a "read-only" command actually contains write/destructive patterns (`rm|mv|cp|mkdir|touch|chmod|dd|>|>>|tee|sed -i|git (commit|push|reset|clean)|sudo|find -delete`, etc.). Never trust a 7B model alone with `rm -rf`. Destructive → print command + explanation → require `y`; abort is recorded in history so "actually yes" works next turn. Refuse interactive commands (`vim`, `top`) and never run `sudo`.

**Model flexibility via two adapters** behind one `Decision` dataclass — the controller never knows which ran:
- *native adapter*: LiteLLM tool-calling (`openai/gpt-4o-mini`, `ollama/mistral:7b`).
- *prompted adapter*: for models without tool-calling (`ollama/llama3:8b`) — tool schemas + "reply ONLY with JSON" in the system prompt, robust JSON extraction (strip markdown fences, regex first `{...}`, one retry feeding the parse error back).

This adapter split *is* the "model flexibility" section and the model-comparison report.

**Chit-chat policy**: off-domain requests (jokes) get a polite **in-role refusal**, not compliance. "How do I X?" shell questions stay in scope (answer without running).

## Intended structure

```
doit                     # entry point: python, no extension, chmod +x, #!/usr/bin/env python3, on PATH
doitlib/
  config.py              # reads ~/doit.cfg — model, provider, temperature, max_steps. Switch model = one line.
  llm.py                 # call(messages, tools) -> Decision; the two adapters live here
  context.py             # assembles the message list; each function maps 1:1 to an ACDL variable (this IS the ACDL)
  controller.py          # the loop: build context -> LPU -> dispatch tool -> append observation -> repeat until answer/step cap (~8). Single-command mode = max_steps=1.
  tools.py               # tool impls; run_command captures stdout/stderr/rc, timeout, truncates to ~4KB for context (full output on disk)
  safety.py              # the regex guard
  state.py               # everything under ~/.doit/
acdl/                    # one spec per phase + rendered screenshots
prompts/                 # prompt templates as files
shell/bashrc_snippet.sh  shell/zshrc_snippet.sh
tests/cases.md           # ~15 fixed cases run against all 3 models
report/
```

**State layout under `~/.doit/`** (keyed by `DOIT_SESSION`, an 8-char per-terminal id):
- `sessions/<id>.jsonl` — one record per turn: `{ts, cwd, request, steps:[{tool,args,stdout,stderr,rc}], final_answer}`
- `memories.json` — `[{id, ts, text}]`
- `shell_hist/<id>` — `ts|cwd|cmd` lines written by the PROMPT_COMMAND (bash) / `precmd`+`fc` (zsh) hook; used for "user awareness". Distinguish user-run vs doit-run commands by cross-referencing the session jsonl.
- `logs/` — full raw LLM requests/responses (report evidence).

## Build order

Follow the phased order in [PLAN.md](PLAN.md) §2 (Phase 0 skeleton → Phase 9 extension → Phase 10 report). **Decisions are locked only through Phase 3; Phases 4–9 need joint review before starting** (see the ⏸ scope note in PLAN.md). Each phase is a phase gate: it is not "done" without its `.acdl` spec and 2–3 logged test interactions committed. **The Phase 9 extension choice (Decision 11) is deferred — do not assume one; it will be decided after Phase 3.**

## Workflow rules

- **Claude never commits.** Git commits are made by the user only. When a phase/part is finished, Claude ends with: (1) a summary of what was built, (2) exact instructions for the user to run and check it themselves, (3) what comes next.

## Ownership

- **[DECISIONS.md](DECISIONS.md)** is maintained by Claude: whenever a design/behavioral/architectural decision is made, revised, or contradicted by evidence during a session, **add or update an entry** (chosen / rejected / why / observed later). The user reviews and edits it freely — never revert their edits.
- **Report prose is written by the user — never draft it.** Curated logs and ACDL drafts may be generated, but the user reviews and owns them.

## Conventions

- **Dual-shell**: auto-detect `$SHELL` (overridable in `doit.cfg`); context includes shell type + OS so the LLM emits portable commands. Both shell snippets write the identical `ts|cwd|cmd` history format.
- **ACDL** (the documentation language, graded): `@T` = turn, `@T.I` = step within turn; `ALL_CAPS` for templates, `camelCase` for functions, `sys/env/resp` namespaces, `T:` role for tool results. Paste specs into the live editor (`https://acdlang26.github.io/acdlsite/visualizer.html`) and screenshot for the report. Because `context.py` is built from named functions, each maps to exactly one ACDL element — preserve that mapping.
- API keys come from env vars, never the repo.
