# Report fix TODO — grouped by mission type

Companion to REPORT_REVIEW.md. Check off as you go. Owner column: split as you like; "run" tasks need a real machine with the shell hooks installed.

## A. Add textual ACDL (highest impact, lowest effort)

- [ ] A1. All sections (1.4, 2.4, 3.4, 4.4, 5.5, 7.5, 8.5, 10.4, 11.5): paste the corresponding `acdl/*.acdl` source as a code listing **next to each figure** (or as Appendix A with per-figure references).
- [ ] A2. Fix `SAFTY_INSTRUCTIONS` → `SAFETY_INSTRUCTIONS` in the .acdl source, re-render, re-screenshot Figure 5.
- [ ] A3. Decide on `env.history` vs `sys.history` (ACDL reference: action histories are `sys.*`) — apply consistently across all specs, re-render affected figures.
- [ ] A4. Section 9: add one line pointing to the history ACDL ("output awareness reuses the replay context of Fig. 4; truncation budgets shown there") or give it its own small spec.

## B. Add prompts, tool definitions, schemas (explicitly required)

- [ ] B1. New Appendix B: full system prompt template(s) — base + the prompted-adapter variant with the JSON-only instruction.
- [ ] B2. Appendix B: contents of every `prompts/*.txt` referenced in the report (memory_block, user_shell_history_block, other_sessions_block, plan/clarify templates).
- [ ] B3. Appendix B: the 8 tool signatures in one table (run_command, answer, ask_user, remember, forget, change_dir, read_session, plan) + the JSON decision schema for the prompted adapter.
- [ ] B4. Section 1 (or new §0): reference the appendix on first use ("full templates in Appendix B").

## C. Run & add real logs (replace staged/hypothetical ones)

**Log-archive audit (2026-07-12):** `bash-llm-agent/logs/` already covers most C tasks — the report just never used them. Status per task: ✅ = exists, paste it; ⚠ = partial; ❌ = must run.

**No old code versions needed for before/after.** All "before" evidence was captured live when the bugs happened; the pairs already on disk:
- phase5: `live_richer_interactions_history_bleed.txt` (before) ↔ `live_richer_interactions_retest_after_prompt_fix.txt` (after)
- phase6_5: `live_change_dir.txt` TEST 3 attempt 1 (wrong-dir `ls`, before) ↔ retest (after), plus the unrequested-`ls` incident + fix at the end of the same file
- phase9: `live_budget_exhaustion_found_pre_fix.txt` (before) ↔ `live_plan_chain_gpt4omini.txt` (after)
- phase6: `behavior_issue.txt` (pre-P6e wrong forget-target) ↔ `live_remaining_cases.txt` BONUS retarget (after)
These pairs are ready-made "what didn't work → how we fixed it" content (feeds F7 too).

- [x] C1. ✅ **COVERED** — `phase9/live_retry_stat_gpt4omini.txt`: real BSD/GNU failure (`stat --format` → exit 1 → retried with `stat -f '%m'`). Also `live_plan_recovery_stop_gpt4omini.txt` (empty `find` → graceful stop, no blind plowing). Paste into §11.4, delete the hypothetical paragraph.
- [x] C2. ✅ **COVERED** — `phase8/live_two_window_gpt4omini.txt`: real ids (p8win1/p8win2), implicit-reference PASS + explicit cross-reference test, raw outputs. Replace §10.3's staged listing.
- [x] C3. ✅ **COVERED** — `phase6/good_interaction_memo.txt`: `doit "tell me a joke"` → "I'm a shell command agent and can't tell jokes...". Paste into §1.3.
- [x] C4. ✅ **COVERED** — `phase3/cmp_gpt4omini.jsonl`: "make my laptop fly" → `answer` tool, "I'm a shell command agent and cannot help with that." Render as a transcript for §1.3/§3.3 (correct-behavior counterpart to gemma3's failure).
- [ ] C5. ⚠ PARTIAL — phase3 cmp runs execute from random tmp dirs and `phase7` case 46 shows cwd-awareness in a nested dir, but no explicit "runs from anywhere" demo. 2-min run: `cd /tmp && doit "what directory am I in?"`.
- [ ] C6. ⚠ CHECK — dual-trigger (`change_dir` + `remember` in one turn) not in the .txt logs; grep `phase6_5/*.jsonl` + `phase6/mem*.jsonl` for a turn containing both tools. If absent: 5-min run of the assignment's exact sentence ("move to X. this is my LLM class project folder").
- [x] C7. ✅ **COVERED** — `phase6/live_remaining_cases.txt` BONUS: "I changed my mind about the sort order — ask me each time" → `forgot m1` + `remembered [m3]`, unrelated m2 untouched. Assignment's exact revision case. Paste into §7.3.
- [x] C8. ✅ **COVERED** — `phase7/live_summarize_gpt4omini.txt`: real zsh hook, "summarize what I just did" with the shell_hist dump proving provenance (+ honest setup-bug note). Paste into §8.3; also `live_cases_45_46_47` (failure recall, cwd, user-vs-doit distinction).
- [ ] C9. ❌ **MISSING** — no log of output-awareness answered via a *follow-up command* (all existing ones answer directly). Run: listing → `doit "which of these looks safe to delete?"` and hope for/prompt a `file`/`du` step. Only genuinely new run in this group.
- [x] C10. ✅ **COVERED** — `phase4/live_multiturn_gpt4omini.txt`: full refinement chain (list → by date → ascending → "by creation time" answered honestly as a BSD limitation — a great limitations exhibit). Paste; optionally add one literal "no, I meant..." turn.
- [x] C11. ✅ **COVERED** — `phase5/live_default_and_no_ask.txt`: genuine ambiguity ("clean up my stuff") → options menu → blank-Enter default → stacked y/N gate → abort; PLUS anti-annoyance negative case (unambiguous request, no question). Replace §5.4's are-you-sure example. Note: MAX_CLARIFICATIONS=2 cap never exercised live (the log says so) — either capture one or state it as untested.

**Bonus finds for other groups:** `phase2/safety_guard_results.json` + `guard_bypass_tests.json` → guard-override numbers for D3/F7; `phase3/prompted_adapter_results.json` → parse/retry rates for D3; `phase3/*_native.txt` vs `*_prompted.txt` → qwen3-vs-gemma3 material for D2; offline suite tallies (change_dir 10/10, memory 14/14, clarify 12/12, history 10/10, prompted 10/10 in `phase6_5/live_change_dir.txt` footer) → D1 results table.

## D. Model comparison (required content, currently a stub)

- [ ] D1. §3.2: run all ~15 `tests/cases.md` cases on gpt-4o-mini, qwen3:4b, gemma3:4b; add a results table (pass / partial / fail per case per model).
- [ ] D2. §3.3: add a qwen3-vs-gemma3 discussion (the required local-vs-local comparison): structured-output reliability, tool-choice quality, destructive flagging accuracy, clarification behavior. At least one transcript where qwen3 succeeds and gemma3 fails on the *same* case.
- [ ] D3. §3.3: report logged numbers: JSON parse-failure/retry rate per model, regex-guard override count per model.
- [ ] D4. §3.1: one sentence explaining the 4B choice (assignment allows 4B tier; hardware/latency rationale) — the plan originally named 7–8B models.
- [ ] D5. §3.1: note any Ollama tool-calling quirks observed with qwen3 native adapter (or state that none appeared).

## E. Elaborate the architecture

- [ ] E1. New §0 "System overview" (~1 page): Controller-wraps-LPU principle, the loop diagram (reuse title-page figure), and the rule "every feature = tool | context block | controller logic".
- [ ] E2. §0: final tool inventory table — all 8 tools in one place with one-line purposes (currently scattered across sections).
- [ ] E3. §0: `~/.doit/` state layout tree (sessions/, memories.json, shell_hist/, logs/) + repo structure.
- [ ] E4. §0: one paragraph on the logging infrastructure (raw LLM traffic in logs/ as report evidence) + where submitted logs live.
- [ ] E5. §1: state which system-prompt blocks exist at v1 (instructions, env block, tools) and forward-reference how later sections only *add context blocks* — the report's best architectural argument, currently implicit.

## F. Limitations & conclusion

- [ ] F1. §1: limitation — cd silently no-ops if the shell snippet isn't installed (mitigated by DOIT_SESSION warning).
- [ ] F2. §2: limitations — regex false positives (`grep "rm -rf" notes.txt`), blind spots (`$(...)` substitution, `xargs rm`), and that sudo/interactive detection is prefix-based.
- [ ] F3. §4: limitation — K=10 window: turns older than 10 are forgotten entirely (mention compaction as the described-but-unimplemented remedy).
- [ ] F4. §5: limitation — empty-input default on a *read-only* command can still surprise; Ctrl-C path only logged, not user-tested at scale.
- [ ] F5. §9: limitation — head/tail truncation loses mid-output content; note the injection surface (shell output entering the prompt is user-controlled text).
- [ ] F6. §10: limitations — 24h recency filter; heuristic one-line summaries can be too thin for faithful cross-session task copying.
- [ ] F7. New final section "Conclusion & what didn't work": synthesis with logged numbers (guard overrides, parse retries), the 2–3 things that surprised you, and honest system limits.

## G. Small mechanical fixes

- [ ] G1. Fix Figure 6 caption collision on p.13 (LaTeX float placement — `[H]` or move the figure).
- [ ] G2. Sweep all listings for staged artifacts (bracketed narration, invented ids) — C1/C2 cover the known ones.
- [ ] G3. Verify every "detailed in the visual ACDL diagram below" phrase now also references the textual listing (after A1).

## H. Partner review notes (Yuval + Arbel, 2026-07-12)

Overlaps with earlier groups are cross-referenced, not duplicated.

### Title page & front matter

- [ ] H1. Title page: remove the architecture diagram from the cover.
- [ ] H2. Fix the diagram and move it into the report body (fits the new §0 overview, → E1): **add the missing arrow from Controller back to User** (output/answer path — currently the loop never returns anything to the user).
- [ ] H3. Add a table of contents.
- [ ] H4. Add an introduction (→ E1).

### Section 1 (single command)

- [ ] H5. State the available tools for the model at this stage (run_command, answer) in §1 body (→ E2, E5).
- [ ] H6. Show the system prompt used in §1 (→ B1; at minimum a short excerpt inline + full text in the appendix).
- [ ] H7. Make the model explicit in the §1 narrative: examples were run with openai/gpt-4o-mini (currently only in the decision box).
- [ ] H8. Example listings expose repo internals (CLAUDE.md, DECISIONS.md rows in Listing 1): re-run the §1 demos in a neutral demo directory with generic files (e.g. tests.py, notes.txt) — **Arbel**. (Also check what the course policy requires about disclosing AI assistance — that's a submission question, separate from demo hygiene.)
- [ ] H9. Add failings/issues subsection to §1 (→ F1).
- [ ] H10. §1 ACDL fixes — **Yuval**:
  - [ ] H10a. `change_dir` reference: move/remove it from the v1 spec (change_dir doesn't exist until later phases; the v1 AVAILABLE_TOOLS comment should list only run_command, answer).
  - [ ] H10b. Clarify in the spec (comment) where tools travel: for the **native** adapter they go out-of-band via the API `tools=` parameter, NOT inside the S: prose; only the **prompted** adapter (Fig. 3) embeds them in the system prompt. Fig. 1 currently shows AVAILABLE_TOOLS inside S:, which is only accurate for the prompted variant — annotate or split.
  - [ ] H10c. Verify "two separate U: messages" (ENV_INFO and user_request as separate user messages in Fig. 1) matches what the code actually sends — check `build_messages` / raw logs; make spec match code (found in the raw log: they ARE two separate user messages — confirm and add a comment saying it's intentional).
- [ ] H11. Insert real logs into §1 (→ C3, C4, C5).
- [ ] H12. Insert a raw model-communication snippet in §1: one request/response JSON from `logs/phase1/llm_raw_p1demo.jsonl` (trimmed), showing the tool_calls object the controller parses.

### Section 2 (dangerous commands)

- [ ] H13. Drop the "Design Decision:" prefix from box titles (or make the box style consistent report-wide — pick one and apply everywhere).
- [ ] H14. The claim "If the guard overrides the model's safety flag, the event is logged for analysis" — back it with a real example or delete it. A real override + counts exist in `logs/phase2/safety_guard_results.json` / `guard_bypass_tests.json` (→ D3): paste one override event and the tally.
- [ ] H15. Re-run the §2 safety flow manually end-to-end ourselves (destructive confirm, guard override, sudo refusal, interactive refusal) to verify current behavior before final submission.
- [ ] H16. §2 ACDL: include the tool definitions in the spec (AVAILABLE_TOOLS comment should enumerate run_command with is_destructive+explanation args — the safety-relevant schema is the point of this section).
