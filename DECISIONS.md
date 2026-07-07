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

## Phase 2 — 2026-07-07

### P2a — safety.py structure: SafetyCheck is the guard's own verdict, not a patch on the model's
Chosen: `check_command()` returns `is_destructive` as the guard's own determination (`model_flag OR regex_match`), plus a separate `guard_overrode_model` bool for reporting. The model's flag can only raise destructiveness, never lower it — matches D5/P1's "guard overrides a false safe claim" design exactly.
Rejected: mutating/returning the model's own flag in place — loses the "how often did the guard actually catch something" metric the report needs.

### P2b — three-way outcome from `_handle_run_command`, not a single boolean gate
Chosen: sudo and interactive commands are hard-refused with no prompt at all (never executable, ever); only genuine destructive-but-legal commands get the `y`/`N` confirmation. Encoded as ordered checks (sudo → interactive → destructive → safe) in `controller._handle_run_command`, each with its own `blocked_reason` recorded in session history.
Rationale: PLAN.md draws this distinction explicitly ("never sudo", "refuse interactive", vs. "destructive → confirm") — collapsing them into one flow would blur a policy difference (no-means-no vs. ask-first) that the report should show clearly.

### P2c — bug found + fixed: `ssh` bare-vs-command detection
Observed during the safety-guard unit tests (logs/phase2/safety_guard_tests.py): my first pass classified any `ssh` invocation as interactive only when it had *exactly one token total* — so `ssh myhost` (2 tokens: program + hostname, no remote command, genuinely interactive) was wrongly let through as non-interactive. Root cause: `ssh` differs from `python`/`mysql`/`psql`, which really are bare with zero arguments; `ssh` is "bare" up to and including the hostname.
Fix: `ssh` gets its own check — strip flag tokens (leading `-`), and treat it as interactive when 0 or 1 non-flag tokens remain (nothing, or just a host). Verified via the unit test: `ssh myhost` → interactive=True, `ssh myhost ls` → interactive=False.
Known residual limitation (documented in code, not fixed): a flag taking a separate value, e.g. `ssh -p 2222 myhost`, is misparsed as a 2-word command and wrongly treated as non-interactive. Accepted as out of scope — a full ssh option table is not worth building for this assignment; flagged in the report's limitations chapter alongside the `grep "rm -rf"` false positive (P2d).

### P2d — accepted false positive: `grep "rm -rf" notes.txt`
Confirmed via the unit test suite: a string literal containing `rm -rf` (e.g. inside a `grep` pattern) trips the guard's `\brm\b` pattern and gets flagged destructive, even though the command is purely read-only. This is the exact case PLAN_DETAILED.md's Decision 5 discussion calls out as an accepted tradeoff of the regex approach (vs. a smarter parser). Left as-is — one extra `y` confirmation on a false positive is a far cheaper failure mode than a false negative on a real `rm -rf`.

### Observed (Phase 2 tests, gpt-4o-mini)
All 12 cases in tests/cases.md pass (logs/phase2/). Notably, gpt-4o-mini never itself attempted a sudo or interactive command in live testing — it already declines those via `answer`, per the system prompt (P1 already established this policy-following behavior). That means the sudo/interactive **guard** code paths were only exercised by directly calling `controller._handle_run_command()` with a hand-built Decision simulating a model that ignored the policy (logs/phase2/guard_bypass_tests.json) — this is the correct way to test defense-in-depth (you must simulate layer 1 failing to prove layer 2 catches it), and worth stating plainly in the report rather than claiming "tested" from live runs that never actually triggered the code path.

### P2e — incident: hand-edited PATH line broke `doit` resolution, then broke it worse
Timeline: Phase 1 setup added `export PATH="$HOME/.local/bin:$PATH"` to `~/.zshrc` so `doit` resolves (P1g #1). Between sessions, Yuval tried editing that line himself and it became `export PATH="$/Users/yuvalreuveni/Documents/Claude/Projects/assingment3/bash-llm-agent/doit$HOME/.local/bin:$PATH"` — `$/Users/...` is not a valid shell variable reference (`$` followed by `/` doesn't expand to anything meaningful), so the whole PATH assignment was corrupted and `doit` stopped resolving again, this time with a broken PATH rather than a merely-missing one.
Fix: restored the line to the original `export PATH="$HOME/.local/bin:$PATH"`; verified with `zsh -lc 'which doit'` in a clean login shell before declaring it fixed, rather than trusting the edit was correct by inspection alone.
Lesson for the report's limitations chapter: this is a second, independent illustration of the same P1g theme (shell/PATH setup is fragile and easy to break by hand) — worth citing both incidents together as one paragraph on "PATH/env setup friction," since Phases 4–9 will add more shell-side hooks (shell_hist, cd wrapper) that are further opportunities for the same class of mistake.

### P2f — observation: conda init block is fully commented out in ~/.zshrc
While debugging P2e, noticed lines 3–16 of `~/.zshrc` (the `# >>> conda initialize >>>` block `conda init` normally manages) are entirely commented out. This explains an earlier session detail: a `(base)`-prompted terminal still resolved `python3` to `/usr/bin/python3` rather than Miniconda's, because conda's own PATH-prepending hook never actually runs on shell startup — the `(base)` prompt was presumably set some other way (or is stale from an old activation). Not a doit bug, not touched — just recorded so a future session doesn't waste time re-diagnosing the same "why does `(base)` not mean what I'd expect" question. Consistent with the multi-interpreter risk already logged in P1g #2.

## Phase 3 — 2026-07-07

### P3a — adapter selected by an explicit `adapter` config key, not auto-detected from the model string
Chosen: `doit.cfg` carries both `model` and `adapter` (`native` | `prompted`); `config.adapter` (default `native`) picks the code path in `llm.call()`. Switching model = the same one-line edit as before, now optionally two lines.
Rejected: auto-detecting the adapter from the model name (e.g. "contains llama3 → prompted"). That buries a model→capability table inside `llm.py`, silently breaks for any new model, and hides the very knob the assignment asks us to demonstrate. Explicit is more honest and matches PLAN_DETAILED's own config sketch (`name = ...` / `adapter = ...`).
Rationale: the two-adapter split IS the "model flexibility" deliverable; making it a visible config choice makes the report's point for us.

### P3b — one `call()` interface, two private adapters, identical `Decision` out
Chosen: `llm.call()` dispatches to `_call_native` (LiteLLM `tools=` + `tool_choice="required"`) or `_call_prompted` (JSON-in-prompt). Both return the same `Decision`; the controller, safety layer, history, and executor are byte-identical across models — the architectural point of the whole phase.
Design detail: the prompted adapter sets `Decision.tool_call_id = None` and stuffs its raw text reply into `assistant_message`. `controller._append_tool_result` branches on `tool_call_id is None` to feed results back as a plain `U:` user message instead of the native `T:` tool role — exactly the v2↔v3 ACDL diff. Unused at `max_steps=1` but correct for Phase 4.

### P3c — prompted adapter: extract → validate → retry-once → raise
Chosen: `_extract_json_object` tries the whole de-fenced reply, then the first *balanced* `{...}` run (a string-aware brace scanner, so braces inside string values don't fool it); `_parse_prompted_reply` then validates the tool name against the real `TOOL_SCHEMAS` names and requires `args` to be an object. Any failure raises `ValueError`; `_call_prompted` retries **once**, appending the bad reply + the parse error (prompts/prompted_retry.txt) so the model can self-correct, then raises `RuntimeError` on a second failure (the entry point shows a clean message; the full exchange is already logged). Implements D6 (JSON format) verbatim.
Rejected: silently coercing a hallucinated tool name or missing args into a best guess — that would hide exactly the failure modes the model-comparison chapter is supposed to surface.
Note: tool schemas are rendered into the system prompt by `_render_tools_as_text` from the same `TOOL_SCHEMAS` the native adapter passes out-of-band — one source of truth, no drift between adapters.

### P3d — offline unit tests stand in for a live Ollama on this machine
Context: Ollama is **not installed** on the dev machine (`which ollama` → not found), so the live three-model suite can't run here yet; that's a user setup step (install Ollama, `ollama pull mistral:7b llama3:8b`).
Chosen: `tests/prompted_adapter_tests.py` proves the adapter's parsing/validation/retry logic against the exact malformed replies weak models emit (fenced JSON, JSON-in-prose, braces-in-strings, hallucinated names, non-object args, garbage-then-valid, two-failures), stubbing `litellm.completion` for the retry path. 10/10 pass under `/usr/bin/python3` (the interpreter that has litellm). Results in logs/phase3/prompted_adapter_results.json.
Rationale: this is the defense-in-depth argument again (P2's guard-bypass tests, restated for the adapter) — you must simulate layer 1 (the model) failing to prove layer 2 (the parser) recovers, and that doesn't need a real model. The *live* cross-model divergence transcripts still need the user's Ollama and are the remaining Phase 3 gate item.

### P3e — local models: qwen3:4b-instruct (native) + gemma3:4b (prompted), replacing the planned mistral:7b / llama3:8b
Changed from the plan's 7–8B pair to the ~4B tier actually installed. Roles preserved exactly: `ollama/qwen3:4b-instruct` is the local **tool-calling** model (native adapter), `ollama/gemma3:4b` is the local **non-tool-calling** model (prompted adapter). The `-instruct` qwen3 tag is the non-thinking variant (avoids reasoning-token noise). No code change needed — `model`/`adapter` are pure config (the whole point of P3a/P3b); only the model strings differ.
Rationale for the swap: smaller/faster to pull and run on this machine while still covering the assignment's required trichotomy (API / local-with-tools / local-without-tools).

### P3f — sanity-checked the local model before running the suite
Before the manual cross-model runs, ran two quick live probes against Ollama (server up on :11434) to retire the top Phase-3 risk (LiteLLM+Ollama tool-calling quirks) up front rather than discovering it mid-suite: (1) native tool-calling on `ollama/qwen3:4b-instruct` returned a clean `run_command` tool call with correct args — so `adapter = native` works with no `ollama_chat/` workaround; (2) the prompted adapter parsed a live Ollama reply end-to-end (qwen3 stand-in until gemma3 finished downloading), returning a Decision with `tool_call_id=None` (the prompted-path marker). Both good — so any oddities in the actual suite are model behavior worth reporting, not plumbing bugs.

### Process: this file's ownership
Originally planned as user-written-only (defense insurance). Changed by Yuval's request: Claude creates and maintains it, adding entries whenever a decision is made or revised during work; Yuval reviews and edits. The insurance now comes from review, not authorship — read every entry critically.

## Phase 4 scope gate lifted — 2026-07-07

### Scope gate: Phase 4 reviewed and locked (Phases 5–9 still pending)
The ⏸ planning scope note (PLAN.md) locked decisions only through Phase 3; Phases 4–9 were "drafted but pending joint review." Yuval reviewed and approved the **Phase 4** scope on 2026-07-07, so the gate is now lifted for Phase 4 only. Locked Phase 4 scope: session history replayed as proper `U:/A:/T:` chat turns (not a text dump), last K≈10 turns kept, older turns dropped; the D7 tiered-truncation budgets below; follow-up vs new-command resolved implicitly by the LLM from context (no classifier); ACDL v4 uses the `ForEach(@t: range(1, @T-1))` history loop. **Phases 5–9 remain gated** — re-review each before starting. Also noted: the Phase 3 gate item CLAUDE.md called "pending" (live 3-model comparison) is in fact done — Ollama is installed and logs/phase3/ holds live gpt-4o-mini / qwen3 / gemma3 runs; CLAUDE.md was stale.

## Pre-decided for later phases — 2026-07-07

### D7 — history output budget: adaptive with tiered truncation (option d), not the metadata cliff
Decided early (belongs to Phase 4+ multi-turn history, made now while the truncation discussion was live). Rejected PLAN_DETAILED option (c), which kept full output for the most recent turn but dropped older turns to metadata-only (command + returncode + first 3 lines). Chosen option (d): **two byte budgets, both head+tail real content** — current/most-recent turn ~3KB head + ~1KB tail; older turns ~1KB head + ~0.3KB tail.
Why: (c)'s metadata floor makes any older turn's output undiscussable, breaking Section 9 output-awareness for follow-ups that refer back more than one turn (e.g. "delete the ones from the first listing") and forcing a "fetch full output" tool. Tiered truncation keeps every past turn's gist (listing start + trailing error) at ~3K tokens for 10 turns vs ~10K for uniform 4KB, with no extra tool — cost is two constants instead of one. Full untruncated output always stays on disk in `logs/`.
Rationale for head+tail sizes: head serves listings (useful content at top), tail serves errors (they print at the end); 1KB head ≈ 15–25 lines, 0.3KB tail ≈ 5–8 lines — enough to catch a `fatal:`/`Permission denied`. To implement in Phase 4: `tools.truncate_for_context` gains a budget parameter; the context builder passes the hot budget for the latest turn and the cold budget when replaying older turns.
Implemented (P4c): `truncate_for_context(text, head_chars=HOT_HEAD, tail_chars=HOT_TAIL)`, budgets `HOT_HEAD=3000/HOT_TAIL=1000` and `COLD_HEAD=1000/COLD_TAIL=300`. Live/current-turn callers use the hot default; `context._replay_turn` passes the cold budget.

### D8 — unanswered clarification: proceed-with-default, split by destructiveness (option a)
Decided now (belongs to Phase 5 `ask_user`); **not yet implemented** — plans updated only. Chosen PLAN_DETAILED option (a): on empty input / Ctrl-C / walk-away after an `ask_user`, proceed with the default the controller already stated — but combined with the destructive-vs-read-only split: **destructive → abort the turn, read-only → run the default.** No timeout.
Rejected: (b) always-abort — maximally safe but annoying for the harmless-default majority; (c) `input()` timeout — signal/`select` fiddliness for negligible value on a CLI the user is actively typing into.
Why: the default is already communicated in the question ("no answer — using modification date"), so honoring it on empty input flows naturally; the read-only/destructive gate keeps the one dangerous case (empty input greenlighting an `rm`/`mv`) safe. To implement in Phase 5: when a clarification loop reads empty/EOF/interrupt, branch on the pending action's destructiveness (reuse the `safety.py` verdict) — read-only proceeds with the stated assumption, destructive aborts and records the abort in session history (so a later "actually yes" works).

## Phase 4 — 2026-07-07

### P4a — history replayed as plain U:/A: messages, NOT the native T: tool role
Chosen: `context._replay_turn` renders each past turn as `user`(request) → `assistant`("$ command") → `user`(output) → `assistant`(final_answer). Even in the native adapter, a past command's output comes back as a `user` message, not a `tool` message.

Root cause — **we don't persist the tool-call ids.** In OpenAI's tool-calling format a `tool` message is not standalone: it's a reply glued to a specific tool call by an id. The assistant that *requests* a call carries `tool_calls: [{id: "call_abc123", ...}]`, and the result must come back as `{role: "tool", tool_call_id: "call_abc123", ...}`. A `tool` message whose id doesn't match a `tool_calls` entry immediately above it is an "orphan" and OpenAI rejects the whole request (HTTP 400). Those ids are ephemeral — they live in the provider's live response object and we throw them away when saving the turn: the session JSONL record is `{ts, cwd, request, steps:[{tool, args, stdout, stderr, rc}], final_answer}` with **no id field**. So when we reload turn #3 a week later we have the command and its output but not the id that a `tool` message would need. Inventing a fake id just produces an orphan. Therefore old output can only re-enter as a plain `user` message.

Rejected: reconstructing real `tool_calls` + `tool`-role messages for history (would require persisting the ids and re-threading them; buys nothing — the model reads plain U:/A: history fine).

Consequence — the `U:`-vs-`T:` distinction is a *within-turn* thing, not a cross-turn thing. Within one live turn we still have the fresh id, so the native adapter uses the real `tool` role (`controller._append_tool_result`, [controller.py]) — that's the v2↔v3 adapter diff. But once a turn is saved and replayed, **all** history is `U:`/`A:` regardless of adapter, because nobody has the ids anymore. Documented in acdl/v4_history.acdl so the ForEach isn't mistaken for emitting real `T:` results. This is a deliberate departure from the PLAN_DETAILED "`T:`/`U:` the output" sketch — that `T:` was conceptual; real API safety forces `U:`.

### P4b — Phase 4 keeps single-command mode (max_steps unchanged), only adds cross-turn history
Chosen: Phase 4 is strictly about *multi-turn* awareness — `build_messages` gained a `session_id` param and prepends `history_messages`; the within-turn loop and `max_steps` default (1) are untouched. A follow-up like "now sort them by date" still emits one `run_command` and ends; history is what makes it pick the *right* command.
Rejected (for now): also raising `max_steps` so a turn could run a command *and then* answer about its output in one turn. That is the separate within-turn agentic loop, not in the locked Phase 4 scope — deferred to avoid scope creep. Records for `answer`-only turns have empty `steps` + a `final_answer`; `run_command` turns have the step + `final_answer=None`; `_replay_turn` handles all three shapes (ran / blocked / answer).

### P4c — build order: system → env(now) → history(last K) → current request
Chosen: history is spliced *between* the ambient env block and the current request so a reference in the request resolves against the turns immediately above it. `K = context.HISTORY_TURNS = 10`; `state.load_recent_turns` returns the last K records oldest-first, skips malformed lines, and returns `[]` when the session file doesn't exist (first turn). The current turn's request is not yet recorded when `build_messages` runs, so there's no self-duplication.
Evidence: offline suite `tests/history_tests.py` (10/10, logs/phase4/history_results.json + history_tests_run.txt) proves replay shape, cold-budget trimming, the K cap (keeps q5..q14 of 15), empty-on-first-turn, and the build order. Live two-turn transcript still to be captured (the report's gold evidence for "now sort them by date").

### P4d — observed on first live multi-turn run (gemma3:4b, prompted): follow-up parroting + session pollution
First real multi-turn run (2026-07-07, `ollama/gemma3:4b`) exposed three things, one per fix:
1. **Follow-up parroting (real behavioral bug).** Across "sort them by date" → "in ascending order" → "in descending order" → "by creation time", the model emitted the *identical* command `ls -la | sort -k 5 -r` every time (only the free-text explanation changed). Two causes: (a) `gemma3:4b` is a 4B model — with ~10 turns of history all showing the same `$` command it pattern-matches and copies rather than reasoning about the refinement; (b) the command was wrong from turn 1 anyway — on `ls -la`, field 5 is the **size** column, so `sort -k 5` never sorted by date. Fixes: reverted `~/doit.cfg` to `openai/gpt-4o-mini` native (the weak local model is a Phase 3 comparison artifact, not the working default); and hardened `prompts/system_prompt.txt` with (i) an explicit "a refining follow-up must change the command, don't copy the previous one" paragraph and (ii) a rule to sort listings with ls's own flags (`-t`/`-tr`/`-S`/`-r`), never `sort -k N`, and to answer (not fake) when asked for BSD creation-time sort. Re-test on gpt-4o-mini pending.
2. **Session pollution (known limitation, not a bug).** `DOIT_SESSION` was unset, so all turns landed in the `"default"` session (P1d fallback) — jokes and tmp.txt create/delete turns leaked into the sort context. The per-terminal id is provided by the shell snippet (Phase 7/8, not yet installed). Interim: set `DOIT_SESSION` manually to isolate a session. This makes the case for building the snippet and for the P1d one-time "no DOIT_SESSION" warning.
3. **K limit works (non-issue).** The transcript *looked* like >10 saved turns, but counting the replayed `user` requests gives exactly 10 history + 1 current — `HISTORY_TURNS=10` is correct. The apparent bloat is that each turn expands to several messages (request + `$ command` + output).
