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

### Process: this file's ownership
Originally planned as user-written-only (defense insurance). Changed by Yuval's request: Claude creates and maintains it, adding entries whenever a decision is made or revised during work; Yuval reviews and edits. The insurance now comes from review, not authorship — read every entry critically.
