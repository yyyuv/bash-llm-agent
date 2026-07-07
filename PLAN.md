# Assignment 3 — `doit` Agentic Shell: Implementation Plan

Target: full marks. The grading text says a *great* submission is distinguished by the **harder agentic parts** (memory, user shell history awareness, multi-terminal sessions, the extension) plus **ACDL documentation done throughout**. This plan front-loads an architecture where those parts fall out naturally instead of being bolted on.

Course grounding (Class 9): `doit` is an **LLM System** — a Controller wrapping an LPU. The LPU only ever sees text and emits structured instructions; the Controller owns the loop, state, tools, and safety. Keep this separation sacred and every later section becomes easy.

---

## 1. Architecture

One Python package, one entry point. Every feature is either a **tool**, a piece of **context**, or **controller logic** — nothing else.

```
                        ┌────────────────────────────────────┐
 user request ──────►   │            CONTROLLER              │
                        │  (agentic loop, max N steps)       │
                        │                                    │
  ┌──────────────┐      │   builds context ──► LPU (LiteLLM) │
  │ STATE (~/.doit)     │   parses response ◄─┘              │
  │  sessions/<id>.jsonl│         │                          │
  │  memories.json      │         ▼ dispatch                 │
  │  shell_hist/<id>    │   ┌───────────────────────────┐    │
  │  logs/*.jsonl       │   │ TOOLS                     │    │
  └──────────────┘      │   │ run_command(cmd, danger)  │    │
                        │   │ ask_user(question, opts)  │    │
  ┌──────────────┐      │   │ remember(fact) /forget    │    │
  │ doit.cfg     │      │   │ change_dir(path)          │    │
  │ (model choice)      │   │ answer(text)  = finish    │    │
  └──────────────┘      │   └───────────────────────────┘    │
                        └────────────────────────────────────┘
```

### Components to build

1. **`config.py`** — reads `~/doit.cfg` (INI or JSON): model name, provider, api base, temperature, max_steps. Switching model = editing one line.
2. **`llm.py`** — single `call(messages, tools) -> Decision` interface over LiteLLM, with **two adapters**:
   - *native adapter*: uses LiteLLM tool-calling (API model, mistral:7b via Ollama);
   - *prompted adapter*: for llama3:8b — tool schemas + "reply ONLY with JSON" in the system prompt, robust JSON extraction (strip markdown fences, regex for first `{...}`, one retry with the parse error fed back).
   Both return the same `Decision` dataclass: `{tool_name, args}`. The controller never knows which adapter ran. **This adapter split is the whole "model flexibility" section and the core of the model-comparison report.**
3. **`context.py`** — assembles the message list each invocation: system prompt (role, tool docs, safety policy) + environment block (cwd, date, session id) + memories + session history + recent user shell history + current request. This file *is* your ACDL: each ACDL context variable maps 1:1 to a function here.
4. **`controller.py`** — the loop: build context → call LPU → dispatch tool → append observation → repeat until `answer` or step cap (~8). Single-command mode (early sections) is just `max_steps=1`.
5. **`tools.py`** — implementations. `run_command` wraps the given `subprocess.run` snippet (capture stdout/stderr/returncode, timeout, truncate output to ~4KB before it enters context — keep full output on disk).
6. **`state.py`** — everything under `~/.doit/`:
   - `sessions/<session_id>.jsonl` — per-terminal history: one record per turn `{ts, cwd, request, steps:[{tool, args, stdout, stderr, rc}], final_answer}`;
   - `memories.json` — list of `{id, ts, text}`;
   - `logs/` — full raw LLM requests/responses (report gold; also your ACDL evidence).
7. **`safety.py`** — see §3.
8. **Shell integration** — dual-shell support (bash on Linux, zsh on macOS): `doit` auto-detects `$SHELL` (overridable in `doit.cfg`) for subprocess execution; context includes shell type + OS so the LLM generates portable commands. Two hook snippets (`shell/bashrc_snippet.sh` with PROMPT_COMMAND, `shell/zshrc_snippet.sh` with `precmd()`/`fc -ln -1`) write the identical `ts|cwd|cmd` history format, keeping everything downstream shell-agnostic. The `doit()` cd-wrapper function is identical in both. bash variant shown (documented shell changes are explicitly allowed):

```bash
# ~/.bashrc — doit integration (documented in report)
export DOIT_SESSION="${DOIT_SESSION:-$(uuidgen | cut -c1-8)}"   # per-terminal session id
export PROMPT_COMMAND='history -a; echo "$(date +%s) $(pwd) $(history 1 | sed "s/^ *[0-9]* *//")" >> ~/.doit/shell_hist/$DOIT_SESSION'
doit() {                                   # wrapper so "cd" can affect THIS shell
  command doit "$@"
  local t=~/.doit/cd_target_$DOIT_SESSION
  [ -f "$t" ] && cd "$(cat "$t")" && rm "$t"
}
```

### The one architectural trap: `cd`

A Python subprocess **cannot change the parent shell's directory**, but the assignment requires `doit "go to my llm class project"` to work. Solution: the `change_dir` tool validates the path, writes it to `~/.doit/cd_target_$DOIT_SESSION`, and the shell-function wrapper above performs the actual `cd` after doit exits. Also record the new cwd in session state so the *next* doit invocation knows where it "is". Document this prominently — it shows you understood the process model.

### Decision schema (the tool set IS the schema)

Do **not** implement `ls`/`grep`/`git` as separate tools (assignment says so). Five tools total:

| tool | args | replaces assignment section |
|---|---|---|
| `run_command` | `command, is_destructive, explanation` | parts 1–2 |
| `ask_user` | `question, options[]` | Clarifications |
| `answer` | `text` | Richer interactions / finish |
| `remember` / `forget` | `fact` / `id` | Memory |
| `change_dir` | `path` | cd trap above |

`answer` doubles as the response for "tell me a joke", "how do I X", and "that's not possible in a shell" — one mechanism covers three required behaviors. **Chit-chat policy (decided):** off-domain requests like jokes get a polite in-role refusal ("Sorry — I'm a shell command agent"), not compliance; "how do I X" shell questions remain in scope.

---

## 2. Build order (each phase = a working, testable agent + its ACDL)

Follow the assignment's own progression; keep each phase's ACDL and 2–3 logged test interactions **before** moving on (grading explicitly punishes retro-fitted documentation).

**Phase 0 — skeleton (½ day).** Repo, `doit` file (python, no extension, `chmod +x`, shebang `#!/usr/bin/env python3`, on PATH via `~/.local/bin`), config loading, LiteLLM hello-world against the API model.

**Phase 1 — single command (1 day).** `max_steps=1`, tools = `run_command` + `answer`. Test: normal command / impossible request / "tell me a joke". ACDL v1.

**Phase 2 — safety (½ day).** See §3. ACDL v2 (adds the confirm branch).

**Phase 3 — model flexibility (1–1.5 days).** Ollama: `ollama pull mistral:7b` (tool-calling) and `ollama pull llama3:8b` (not). Build the prompted adapter (JSON format — decided), run the *same* test suite on all three models, save divergent transcripts — this is the required model-comparison section. LiteLLM model strings: `ollama/mistral:7b`, `ollama/llama3:8b`, and `openai/gpt-4o-mini` for the API model (decided — paid key available; key via env var, not in repo).

> **⏸ Planning scope note:** decisions are locked through **Phase 4** (Phase 3 checklist in PLAN_DETAILED.md: cd wrapper, JSONL, dual-shell, OpenAI, in-band safety flag + guard with judge fallback, JSON prompted format, polite-refusal chit-chat policy — plus Phase 4 reviewed & locked 2026-07-07: multi-turn history replayed as `U:/A:/T:` chat turns, last K≈10 turns, D7 tiered-truncation budgets, ACDL v4 `ForEach` history loop). Phases 5–9 below remain drafted but pending joint review — discuss before starting them.

**Phase 4 — multi-turn (1 day).** Session history in context ("now sort them by date", "no, latest first"). Include per-turn: request, commands run, truncated outputs. ACDL v3 uses `ForEach(@t: range(1, @T-1))` — exactly the pattern from the syntax reference.

**Phase 5 — clarifications + richer interactions (1 day).** `ask_user` tool; timeout/empty answer → proceed with stated default. Anti-annoyance: system prompt says ask *only* when the wrong guess would be destructive or the request is truly ambiguous. Richer interactions come free via `answer` + history ("modify it to do y" → new `answer`; "execute it" → `run_command`).

**Phase 6 — memory (1 day).** `remember` tool + memories injected into system context. The combined case ("move to X. this is my project folder") works because the loop allows `change_dir` *then* `remember` in one turn. Memory edits ("I changed my mind…") = `forget` + `remember`.

**Phase 7 — user awareness (1 day).** Read `~/.doit/shell_hist/$DOIT_SESSION` (from the PROMPT_COMMAND hook: timestamp + cwd + command). Distinguish doit-run vs user-run commands: doit's own commands are in session jsonl; anything in shell_hist not matching them is the user's. Context gets a labeled block: "Recent commands the USER ran manually". Test: the assignment's exact `summarize what I just did` scenario.

**Phase 8 — multi-tasking (1 day).** Already 90% done because state is keyed by `DOIT_SESSION` from Phase 0. Add: context contains *this* session's history in full + a one-line summary of other recent sessions ("Session b3f2 in ~/Documents: created year folders 2020–2026"), so explicit cross-references ("the same folder task we did in window 2") resolve, while implicit references ("sort them") stay local. Test with two terminals using the assignment's exact scenario.

**Phase 9 — extension (1 day).** Describe three, implement one:
   1. **Command plans / multi-step execution** *(implement this)* — one request → LPU proposes a short plan, then executes commands sequentially, feeding each output back, recovering from failures (e.g. "find the largest 3 log files anywhere under ~/projects and compress them"). It's a real agentic capability (planning + recovery), and your controller loop already supports it — you mostly *unlock* it (`max_steps>1` for command chains) + add a plan-preview confirmation for destructive sequences.
   2. Context compaction: summarize sessions older than K turns via a separate LLM call (`summarize(prompt.History[@t])` — literally an ACDL function).
   3. Project profiles: a `.doit.md` per directory (agent.md equivalent), auto-loaded into context when cwd is inside that project.

**Phase 10 — report + polish (2 days).** Don't compress this; the report is half the grade.

Total ≈ 9–10 working days. If time-crunched, phases 4–8 are where the grade lives; phase 3's prompted adapter is the riskiest item, so do it early, not last.

---

## 3. Safety design (identifying dangerous commands)

Defense in depth — two layers, and say so in the report:

1. **LLM self-report**: `run_command` has a required `is_destructive` boolean + `explanation`. Zero extra latency vs. the assignment's suggested "separate LLM call", and works identically across all three models. (Mention in the report you considered a separate classifier call and why you chose this: cost, latency, and the flag is in the same JSON the weak model already produces.)
2. **Deterministic guard**: regex/parse check in Python that *overrides* the model when it flags read-only but the command contains `rm|mv|cp|mkdir|touch|chmod|chown|dd|>|>>|tee|ln|sed -i|git (commit|push|reset|clean)|curl.*\|.*sh|sudo`. Never trust a 7B model alone with `rm -rf`.

Flow: destructive → print command + explanation → `y` to run, anything else aborts (and the abort is recorded in history so "actually yes, do it" works next turn). Watch edge cases for the report: pipes hiding writes (`ls | tee f`), redirects, command substitution, `find -delete`.

Also handle: interactive commands (`vim`, `top` — detect and refuse with an `answer`), `sudo` (never run), timeout (from the snippet: catch `TimeoutExpired`, report gracefully).

---

## 4. ACDL strategy (do this as you go — it's explicitly graded)

Keep `acdl/` in the repo with one spec per agent version (`v1_single.acdl` … `v9_extension.acdl`). After each phase: write the spec, paste into the [live editor](https://acdlang26.github.io/acdlsite/visualizer.html), screenshot the rendering for the report. Because `context.py` builds context from named functions, each function maps to exactly one ACDL element — state this mapping in the report; it's precisely the "compare report ↔ code behavior" property the grader asks for.

Sketch of the final version (adjust as you build):

```
DoitAgent[@T, I]: {
    S: {
        AGENT_INSTRUCTIONS            // role, safety policy, when to clarify
        AVAILABLE_TOOLS               // 5 tool schemas
        SAFETY_POLICY
    }
    U: {
        env.cwd[@T]                   // from cd-tracking
        env.datetime[@T]
        env.session_id
        ForEach(m: sys.memories) { sys.memory_text[m] }
        ForEach(s: sys.other_sessions) {
            summarize(prompt.History[s])      // cross-terminal awareness
        }
    }
    ForEach(@t: range(1, @T-1)) {             // this session's turns
        U: env.user_request[@t]
        ForEach(i: range(1, @t.substeps)) {
            A: sys.tool_call[@t.i]
            T: truncate(sys.tool_response[@t.i])
        }
        A: resp.final_answer[@t]
    }
    U: {
        USER_SHELL_HISTORY            // labeled: commands run manually by user
        ForEach(h: env.recent_user_commands[@T]) { env.shell_cmd[h] }
    }
    U: env.user_request[@T]
    ForEach(i: range(1, I)) {                 // current turn's steps so far
        A: sys.tool_call[@T.i]
        T: truncate(sys.tool_response[@T.i])
    }
}
```

Note the conventions used (they're graded details): `@T` = turn, `@T.I` = step within turn (Class 9's multi-step/multi-turn distinction, verbatim), `ALL_CAPS` templates, `camelCase` functions, `sys/env/resp` namespaces, `T:` role for tool results.

For the prompted adapter (llama3), write a *separate* spec where tool schemas live in `S:` as text and tool results come back as `U:` — the visual diff between the two specs is a ready-made, high-quality report figure.

---

## 5. Model comparison plan (required in report)

Fixed test suite (~15 cases) in `tests/cases.md`, run against all three models, transcripts auto-saved by the logger:

- simple command; command with pipes; impossible request; joke/chat; dangerous command; ambiguous request (should clarify); multi-turn refinement ×3; memory store+recall; user-history question; cross-session reference; multi-step extension case; malformed-output recovery.

What to look for (and write up): llama3:8b breaking JSON (fences, trailing prose, hallucinated tool names), over-eager clarifications, wrong `is_destructive` flags rescued by the regex guard, retry-on-parse-error saving it. Include at least one full failure transcript + how the system recovered — the assignment asks for exactly this.

---

## 6. Report skeleton

Per assignment section: what was implemented → design decisions (with the *rejected* alternative and why) → ACDL text + visual → prompt templates verbatim → ≥1 interesting logged interaction → limitations. Then: model comparison chapter, `.bashrc` changes documented, extension chapter (why chosen, how built, one interaction where it matters), honest limitations chapter (cd wrapper requirement, truncation losing info, safety false positives/negatives, session id lost in subshells/tmux, prompt-injection via file contents in shell output — mentioning that last one signals real understanding).

---

## 7. Risk register

| Risk | Mitigation |
|---|---|
| llama3:8b won't emit clean JSON | prompted adapter with extraction + 1 retry feeding back the parse error; document failures — they're report content, not embarrassments |
| `cd` can't affect parent shell | shell-function wrapper (§1); test early |
| Ollama+LiteLLM tool-calling quirks with mistral | prompted adapter is a universal fallback for any model; verify in Phase 3, not Phase 9 |
| Huge command outputs blow context | truncate to ~4KB head+tail in context, full output on disk, `answer` can say "output truncated, N lines total" |
| Safety misclassification | regex override layer; log every override |
| History file grows unbounded | cap turns in context (K=10) + extension #2 (compaction) if implemented |
| ACDL left to the end | phase gate: no phase is "done" without its .acdl + logged tests |
| API costs | use small model (gpt-4o-mini / gemini-flash free tier); local models are free |

---

## 8. Repo layout

```
doit/
├── doit                  # entry point, no extension, executable
├── doitlib/
│   ├── config.py  llm.py  context.py  controller.py
│   ├── tools.py  safety.py  state.py
├── acdl/                 # v1..v9 specs + rendered screenshots
├── prompts/              # prompt templates as files (report copies from here)
├── shell/bashrc_snippet.sh
├── tests/cases.md
├── logs/                 # curated interaction transcripts for report
└── report/
```

First concrete step: Phase 0 + Phase 1 against the API model — everything else layers onto that loop.
