# Report review — pros, cons, and prioritized improvement list

Reviewed against the assignment's explicit submission requirements and grading text (report.pdf, July 9 version, 20 pp).

## Pros (keep these)

- Structure mirrors the assignment sections exactly, and every section follows the same discipline: implementation → design-decision boxes → example → ACDL. Graders can tick requirements off linearly.
- The design-decision boxes are the report's strongest feature — each names the **rejected alternative** and the rationale (in-band flag vs. judge call, JSONL vs. SQLite, summaries+fetch vs. full injection, opt-in plans vs. global budget). This is precisely what "explain your design choices" means.
- Real failure analysis exists: gemma3's `echo "...""` shell-parse crash on the impossible request, and the JSON de-fencing recovery log. Honest limitations in §6.3 (weak models fail "execute it") and §7.4 (memory ID recycling).
- ACDL figures are genuine visualizer renders and the later ones are rich — Figure 5 correctly shows `@T.I` turn/step indexing, `ForEach` over history, `If/ElseIf` role assignment by tool type, `truncate()` as a function, `T:` roles. This is above-average ACDL work.
- The harder agentic parts are all present with sensible designs: tiered HOT/COLD truncation, per-session streams + `read_session` fetch tool, context-ordering for pronoun locality, opt-in plan budgets with self-correcting retry.
- The stacked-safety example (clarification → confirmation gate) shows mechanisms composing, which the grading text rewards ("how well the different parts fit together").

## Cons — gaps against explicit requirements

1. **No textual ACDL anywhere.** The assignment: "include both the textual description, as well as the generated visual representation." Only screenshots are present. This is the single largest predictable point loss, and the cheapest to fix — the `.acdl` sources already exist in `acdl/`.
2. **No prompt templates, tool definitions, or schemas.** Explicitly required ("The prompt templates, tool definitions, structured-output formats, or schemas used by your system"). The report *references* `prompts/*.txt` files five times but never shows one; the JSON decision schema and the 8 tool signatures are never listed.
3. **The model comparison is a stub.** §3.2 says "We evaluated three models using the test suite in tests/cases.md" — and then shows no results. Missing: a per-case results table (pass/partial/fail × 3 models), any observation about **qwen3:4b** at all (the comparison is required to be between the *two local* models — currently only gemma3 is discussed), and discussion of divergences in clarification behavior / destructive flagging / error handling, which the assignment names specifically.
4. **The extension's key evidence is hypothetical.** §11.4's "self-correction example" literally says *"If 'touch' failed... the model would"*. The assignment requires "at least one interaction where the extension matters" — a real one. Force a genuine failure (e.g. a command using a missing utility, or mkdir into a non-writable path) and paste the raw retry transcript.
5. **Several logs look staged, not raw.** `read_session("Terminal_2")` (real session ids look like `f4a2c9d1`), "Folders created.", and bracketed narration `[Implicit reference resolves locally...]` inside listings. The grading text emphasizes "good use of logs" — staged-looking transcripts undermine trust in all the others. Re-run these and paste verbatim output.
6. **Missing flagship examples the assignment itself names:**
   - "tell me a joke" → the polite in-role refusal is never demonstrated (only policy-stated; the only impossible-request transcript is gemma3's *failure*). Show the correct behavior on the API model too.
   - Memory dual-trigger: "move to X. **this is my project folder**" → `change_dir` + `remember` in one turn (§7's design supports it; the example shown is a plain explicit "remember").
   - Memory revision: "I changed my mind... ask me each time" → `forget` + `remember`.
   - User awareness: `doit "summarize what I just did"` — the assignment's exact example; also demonstrate distinguishing user-run vs doit-run commands (the current example only touches the last error).
   - Output awareness via *further commands*: the assignment says such questions can be answered "either by the LLM directly, **or by invocation of further shell commands**" — only the direct path is shown (and "which of these is larger?" is a weak question; the answer is visible in the listing). Better: "which of these looks safe to delete?" where the model runs `file`/`du` first.
   - Multi-turn correction: "no, I meant latest first" style repair turn.
7. **No architecture overview.** The title page has a small diagram, but the Controller/LPU principle, the final tool inventory (it's 8 tools by the end — run_command, answer, ask_user, remember, forget, change_dir, read_session, plan — never enumerated in one place), and the repo/state layout (`~/.doit/` tree) are nowhere. One page before §1 would orient the grader and showcase the report's best argument: one loop, everything else is a tool or a context block.
8. **Limitations subsections missing in §1, 2, 4, 5, 9, 10.** The assignment requires limitations per section. Cheap content that already exists in your DECISIONS.md: cd silently no-ops without the snippet (§1); regex guard false positives and `$(...)`/`xargs rm` blind spots (§2); K=10 window forgetting older turns (§4); empty-answer default risk (§5); truncation losing mid-file content (§9); 24h recency filter and summary staleness (§10).
9. **No conclusion / "what didn't work" chapter.** Grading text: "what worked, what did not work, and what the limitations of your system are." Scattered limitations exist, but there's no honest closing synthesis (e.g., prompted-adapter reliability numbers, guard override counts — both are logged, so report the numbers).

## Smaller fixes

10. §5.4's clarification example is a poor showcase: "delete the logs" → "Are you sure?" duplicates the confirmation gate — the exact annoyance §5.3 claims to prevent. Replace with genuine ambiguity (the assignment's own sort-by-date case) and keep the stacked example as a *secondary* one, reframed as scope clarification (which logs?).
11. Figure 5 typo: `SAFTY_INSTRUCTIONS` → `SAFETY_INSTRUCTIONS` (it's in the rendered ACDL, so fix the .acdl and re-screenshot).
12. Namespace check: history is rendered as `env.history[...]` — per the ACDL reference, action histories/agent state belong to `sys.*` (`env` is external observations). Arguable, but an easy consistency win; graders wrote the spec.
13. Figure 6's caption collides with page text ("13ACDL context for memory injection") — LaTeX float placement issue on p.13.
14. §9 has no ACDL figure or pointer — add one line pointing to Figure 4/5 ("output awareness reuses the history-replay context; see truncate() budgets in Fig. 4").
15. Model switch is unexplained: the plan targeted mistral:7b/llama3:8b, the report uses qwen3:4b/gemma3:4b. Fine per the assignment (4B tier), but add one sentence of rationale (hardware/latency), otherwise it reads as arbitrary.
16. §3.1 table lists qwen3:4b-instruct as Native — if any tool-calling quirks appeared with Ollama's tool support, mention them; if none, say so (it's evidence, not filler).
17. "It should be added to your path" / invocation-from-any-directory is claimed but never shown — a two-line transcript from a random cwd (`cd /tmp && doit ...`) closes it.

## Prioritized action list

| # | Action | Effort | Grade impact |
|---|--------|--------|--------------|
| 1 | Add textual ACDL beside every figure (appendix or inline listings) | Low — files exist | High |
| 2 | Add appendix: prompt templates + tool schemas + JSON decision format | Low — files exist | High |
| 3 | Real per-case results table for the 3 models + qwen3-vs-gemma3 discussion | Medium — suite exists, run it | High |
| 4 | Replace hypothetical retry with a real failure→recovery transcript | Low | High |
| 5 | Re-run and paste raw logs for §10 (and any other staged-looking listing) | Low | Medium-high |
| 6 | Add the missing flagship examples (joke refusal, dual-trigger memory, memory revision, "summarize what I just did", output-awareness-via-command, correction turn) | Medium | Medium-high |
| 7 | Add 1-page architecture overview with final tool inventory + state layout | Low | Medium |
| 8 | Add limitations subsections to §1,2,4,5,9,10 + a short conclusion with logged numbers (guard overrides, parse-retry rate) | Medium | Medium |
| 9 | Items 10–17 above | Low each | Low-medium |

## What to delete

Almost nothing — the report is lean, which is good. Only: the hypothetical self-correction paragraph (replaced by a real log), and the bracketed narration inside listings (replace with raw output; explanatory prose belongs outside the listing).
