# DECISIONS.md — design decision journal

Maintained by Claude during work sessions; Yuval reviews and edits freely.
One entry per decision: what was chosen, what was rejected, why, and anything observed later that confirms or challenges it. This file feeds the report's "design decisions / what worked / what didn't" sections directly.

---

## Planning phase — 2026-07-06

### Architecture: Controller wrapping an LPU, everything is a tool
Chosen: strict Class-9-style separation — Python controller owns loop/state/safety; the LLM only emits structured decisions. Five tools (`run_command`, `answer`, `ask_user`, `remember`/`forget`, `change_dir`) cover every assignment section.
Rejected: a tool per shell command (assignment explicitly warns against it); ad-hoc per-feature mechanisms.
Rationale: one contract for all 3 models; later assignment sections become add-ons, not rewrites.

### D1 — cd handling: shell-function wrapper
Chosen: `change_dir` writes target to `~/.doit/cd_target_$DOIT_SESSION`; a `doit()` function in bashrc/zshrc performs the real `cd` after exit.
Rejected: (b) not supporting cd — fails the assignment's explicit example; (c) `eval "$(doit ...)"` — awkward and unsafe.
Known weakness: silently no-cd without the snippet → mitigated by a one-time warning when `DOIT_SESSION` is missing.

### D2 — storage: JSONL files under ~/.doit/
Rejected: SQLite (better queries, but less debuggable/greppable; overkill at this scale).
Rationale: human-readable state helps debugging and the report; appends are trivial.

### D3 — shell support: both bash and zsh, auto-detect
Context: one partner on Linux/bash, one on macOS/zsh.
Design rule: normalize at the boundary — two hook snippets write the identical `ts|cwd|cmd` format; everything downstream is shell-agnostic. Context tells the LLM shell type + OS (BSD vs GNU tools) and asks for portable syntax.

### D4 — API model: OpenAI gpt-4o-mini
Rationale: paid key already available; most-tested LiteLLM path; reliable tool calling.
Rejected: Gemini free tier (rate limits during heavy testing), Anthropic (no key at hand).

### D5 — safety: in-band `is_destructive` flag + deterministic regex guard
Chosen: model self-reports destructiveness in the same JSON; Python guard overrides false "safe" claims. Every override is logged (report metric).
Rejected for now: separate LLM judge call (assignment's hint) — doubles latency/cost, and the guard is needed anyway. **Escalation path agreed: if testing shows the flag is unreliable, add the judge call.**

### D6 — prompted-adapter format: JSON
Rejected for now: XML-ish tags. If llama3:8b's JSON failure rate proves unbearable, tags become a documented experiment (report content either way).

### Chit-chat policy: polite in-role refusal
Off-domain requests ("tell me a joke") get "Sorry — I'm a shell command agent", not compliance. "How do I X?" shell questions remain in scope.
Noted risk: assignment says "respond nicely" to such requests, which could be read as "play along". We judge a polite refusal satisfies it (nicely ≠ compliantly) and will state the rationale in the report.

### Scope gate
Decisions locked through Phase 3 only. Phases 4–9 drafted in PLAN_DETAILED.md but pending joint review. Open: D7 (output in history), D8 (unanswered clarifications), D9 (memory injection), D10 (cross-session awareness), D11 (extension choice — decide after Phase 3, once local-model competence is known).

## Phase 0 + 1 — 2026-07-07

### P1a — every LLM reply must be a tool call (`tool_choice="required"`)
Chosen: the native adapter forces a tool call, so `answer` is genuinely the only way to talk and the controller never parses free text. A plain-text reply (should the provider ignore the constraint) is defensively wrapped as an `answer` Decision.
Rejected: allowing free-text replies alongside tool calls — two output channels would complicate the loop and the ACDL for no benefit.

### P1b — Decision carries the provider message (`assistant_message`, `tool_call_id`)
Chosen: `llm.call()` returns the raw assistant message alongside `{tool_name, args}`, so the controller can append tool results using the provider's native tool protocol. Unused at `max_steps=1` but makes Phases 4–5 (multi-step, ask_user) a config change, not a rewrite.
Rejected: re-serializing tool results as plain user messages — breaks native tool-calling models' expectations.

### P1c — environment block is its own user message
Two consecutive `U:` messages (env block, then request) instead of one concatenated message, preserving the 1:1 `context.py` function ↔ ACDL element mapping. OpenAI accepts consecutive user messages.

### P1d — session id fallback
`DOIT_SESSION` unset → session id `"default"` so doit works before the shell snippet exists (snippet arrives with the cd wrapper). The D1 one-time warning is deferred to that phase too.

### P1e — environment/install choices
System Python 3.9.6 + `pip3 install --user litellm` (no venv — the `#!/usr/bin/env python3` shebang then just works); entry point symlinked into `~/.local/bin`. `OPENAI_API_KEY` lives in a gitignored `.env` at the repo root, sourced by the shell — never committed.

### Observed (Phase 1 tests, gpt-4o-mini)
All 5 cases in tests/cases.md behaved correctly (logs/phase1/). One nuance: "make my laptop fly" was refused as *off-topic* rather than explained as *impossible* — acceptable behavior, but track it in the Phase 3 model comparison.

### P1f — system prompt fix: "edit" was misread as opening an interactive editor
Observed: `doit "edit test.txt file to say hello"` returned `answer` (just described `echo "hello" > test.txt`) instead of running it, while `doit "write in test.txt 'abc'"` correctly ran. Root cause: the interactive-programs rule ("never run vim, nano...") made the model treat "edit" as edit-in-an-editor and back off to explaining.
Chosen: two prompt additions in prompts/system_prompt.txt — (1) an explicit line that concrete actions (create/write/edit/move/delete/install/...) must use `run_command`, not `answer`; (2) a carve-out on the interactive-programs rule stating that changing a file's contents via non-interactive commands (echo/redirection, sed, heredoc) does not count as "interactive." Fix #1 alone was insufficient; #2 resolved it. Re-verified: joke refusal and "how do I see hidden files?" still behave correctly (no regression).
Rationale for keeping this in the report: a good example of a genuine word-sense ambiguity a 7B prompted-adapter model may hit even harder in Phase 3 — worth re-testing there.

### P1g — environment friction observed during setup (report gold for "limitations")
Three separate gotchas hit during Phase 1 verification, none of them code bugs — all worth a paragraph in the report's honest-limitations section:
1. **`~/.local/bin` wasn't on Yuval's PATH.** Fixed by appending `export PATH="$HOME/.local/bin:$PATH"` to `~/.zshrc`. Any grader without that line will hit `command not found: doit` on a fresh machine — worth a one-line setup note in the eventual README.
2. **Two Python interpreters, one `pip install`.** `litellm` was installed for system `/usr/bin/python3`, but Yuval's terminal defaults to Miniconda's `base` env (`(base)` prompt) which has its own `python3` and no `litellm` → `ModuleNotFoundError`. Resolved by `conda deactivate`. Because `doit`'s shebang is `#!/usr/bin/env python3`, *whichever* `python3` is first on PATH at invocation time is the one that runs — this is inherent to the shebang choice, not fixed by anything in the repo. Document this as a known environment dependency.
3. **`source .env` alone does not export.** Without `export`/`set -a`, `KEY=value` in a sourced file only becomes a *shell* variable, invisible to child processes like the `doit` Python subprocess → `litellm.AuthenticationError` even though `echo $OPENAI_API_KEY` looked fine to a casual glance (it wasn't set at all, actually — the real symptom was an empty var). Correct invocation: `set -a; source .env; set +a`. Worth a one-line comment at the top of `.env` itself so future-us doesn't relearn this.

### Watch list for later phases
Open threads from Phase 0+1 that later phases should re-examine, not just this file's already-tracked ⏸ decisions:
- **Action vs. explain judgment (P1f)** — re-run a broader set of "ambiguous verb" requests (edit/change/update/fix/clean) against mistral:7b and llama3:8b in Phase 3; the weaker/prompted-adapter models may need the same carve-out spelled out even more explicitly, or may need it in the *tool description* rather than free prose.
- **`is_destructive` self-report reliability** — Phase 1 only saw one destructive case (`echo > test.txt`, correctly flagged true). Phase 2's regex guard needs a real adversarial test set (pipes hiding writes, `find -delete`, `git reset`) before trusting the flag's accuracy number in the report.
- **Environment friction (P1g) as a report figure** — Phases 4–9 will add more shell-side state (shell_hist hook, cd wrapper); each new piece of shell integration is a new place for PATH/env-export surprises like the three above. Worth keeping a running list rather than rediscovering the pattern each phase.

### Process: this file's ownership
Originally planned as user-written-only (defense insurance). Changed by Yuval's request: Claude creates and maintains it, adding entries whenever a decision is made or revised during work; Yuval reviews and edits. The insurance now comes from review, not authorship — read every entry critically.
