# Report fix TODO — grouped by mission type

Companion to REPORT_REVIEW.md. Check off as you go.

---

## STATUS SUMMARY (updated 2026-08-09)

**Done this session (in `report/report.tex` unless noted):**
- **A (ACDL):** A1 ✅ (listings next to every figure), A2 ✅ (SAFTY→SAFETY, re-rendered), A3 ✅ (`sys.history` across all specs). ACDL specs fully rewritten to the context-only convention.
- **B (prompts/schemas):** B1 ✅, B2 ✅, B3 ✅ — Appendix A now has: real base prompt + per-version deltas (from git) + full final prompt, all 7 `prompts/*.txt`, the 8-tool table + full `TOOL_SCHEMAS` from `tools.py`.
- **C (real logs):** C1–C11 ✅ all covered (logs on disk + curated).
- **D (model comparison):** D1 ✅ (results table now in §4), D3 ✅ (logged numbers in §4). Data source: `report/model_comparison_data.md`.
- **G:** G2 ✅ (staged §11/§12/§2 examples replaced with real logs), G3 ✅ (listings sit next to each figure).
- **H:** H10a/b/c ✅ (v1 ACDL fixed), H14 ✅ (real guard-override + 6/15 tally in §2), H1–H4 ✅ (front matter: cover diagram removed, moved into §1 with Controller→User arrow, TOC, intro).
- **F (limitations):** F1–F6b ✅ (per-section Limitations added to §2/§3/§4/§5/change_dir/§10/§11/§12; §6/§7/§9 already had them).

**Still needed — see groups below.** Biggest gaps: overview depth (E1 DONE via the §1 intro, but E2 tool-inventory table / E3 state-layout tree / E4 logging paragraph / E5 v1-blocks note are still owed), Conclusion (F7). Front matter DONE: title-page diagram removed (H1), diagram moved into §1 with the Controller→User arrow (H2), TOC added (H3), intro added (H4). Per-section Limitations (F1–F6b) DONE — added to §2/§3/§4/§5/change_dir/§10/§11/§12 (§6/§7/§9 already had them).

> **Compile note:** no LaTeX on the dev machine — the `.tex` has NOT been compiled/verified yet. `cd report && pdflatex report.tex` ×2 (or Overleaf with `report/`+`acdl/`+`prompts/`+`doitlib/` siblings). Watch the first run for errors.

---

## A. Textual ACDL

- [x] A1. ✅ DONE — `acdl/*.acdl` source shown as `\lstinputlisting` next to every figure (auto-syncs).
- [x] A2. ✅ DONE — `SAFETY_INSTRUCTIONS` spelling fixed in source; figures re-rendered by Yuval.
- [x] A3. ✅ DONE — settled on `sys.history` (corpus: action histories are `sys.*`), applied to all specs.
- [x] A4. ✅ DONE — added an "ACDL Context" pointer to BOTH §Richer interactions and §Output awareness (the two sections with no ACDL figure): each notes it adds no new context block and points to the history spec `fig:acdl_v4`. Closes the "missing ACDL coverage" question for those sections.

## B. Prompts, tool definitions, schemas

- [x] B1. ✅ DONE — Appendix A: real base prompt + per-version git deltas + full final `system_prompt.txt` + prompted-adapter `prompted_suffix.txt`/`prompted_retry.txt`.
- [x] B2. ✅ DONE — all 7 `prompts/*.txt` included (`environment_block`, `memory_block`, `user_shell_history_block`, `other_sessions_block`, + the three above).
- [x] B3. ✅ DONE — 8-tool signature table + JSON decision shape + full `TOOL_SCHEMAS` listing (`doitlib/tools.py` lines 36–282).
- [ ] B4. §1 (or new §0): add a one-line forward-reference to Appendix A on first mention of the prompt/tools. *(Prose — small.)*

## C. Real logs

**All done.** C1–C11 ✅ (evidence on disk; the real ones are now spliced into §2/§4/§11/§12 — see G2). Remaining "paste into section X" notes are absorbed into the prose still owed for those sections.

**What-worked/didn't bug-fix cases now IN the report (2026-08-10, real data from `report/*.md`):**
- **§Richer interactions** — added "What Worked and What Didn't: the Repeated-Question Bug" (the history-bleed bug): buggy 3-turn transcript → failed separate-paragraph fix → root cause (two rules conflicting by proximity/specificity) → the in-rule fix that worked → lesson. Source: `report/history_bleed_bug.md`, logs/phase5/.
- **§Output awareness** — added the stronger follow-up-command example (runs `file …` instead of guessing) + two honest behavioral limitations (non-deterministic single-command batching; facts ≠ good delete verdict). Source: `report/output_awareness_followup*.md`, logs/phase9/.

**Three more bug/fix cases (2026-08-10, built from logs/sessions):**
- [x] `report/plan_budget_exhaustion_bug.md` (Phase 9 P9e) — **INSERTED** into §Further extensions as "What Worked and What Didn't: a Plan that Stopped Halfway" (shortened/simplified per Yuval).
- [x] `report/wrong_forget_parallel_toolcalls_bug.md` (Phase 6 P6e) — **INSERTED** into §Memory as "What Worked and What Didn't: a Memory Edit that Crashed" (shortened/simplified).
- [ ] `report/change_dir_same_turn_bug.md` (Phase 6.5 P6.5b/d) — **source file only, NOT inserted** (deliberately skipped: its point-of-decision lesson is already made + cross-referenced in §Richer and §Changing directories). Fold a 1–2 sentence mention into §Changing directories' Limitations if wanted.

## D. Model comparison

- [x] D1. ✅ DONE — per-case results table (V/~/X, 10/7/6) is in §4 "Case-by-Case Results".
- [x] D2. ✅ DONE — new §Model flexibility subsection "Local-vs-Local Head-to-Head: qwen3 vs gemma3" with real transcripts: qwen wins case 57 (correct pipeline vs gemma over-flagging), gemma wins case 5 (gemma answers vs qwen wrongly executes), + a stability/structured-output paragraph (gemma run-to-run instability, qwen 0 JSON failures). Directly satisfies the assignment's required tool-vs-non-tool local comparison with a weaker-model-fails interaction.
- [x] D3. ✅ DONE — logged numbers (guard 6/15, parser 10/10, live JSON failures) are in §4 "Logged Reliability Numbers".
- [x] D4. ✅ DONE — sentence added after the model table: used the ~4B tier the assignment permits rather than the plan's 7–8B, because we served models locally and downloading/running larger ones on our own machines was too slow (Yuval's reason).
- [x] D5. ✅ DONE — qwen native over-caution (refused to list a `/tmp` sandbox, case 1) is in the head-to-head "Stability and structured output" paragraph.
- [x] D6. ✅ DONE — gemma3 history-parroting inserted as a short "History parroting" paragraph in the §Model flexibility head-to-head (gemma repeats `ls > files.txt` for install htop / open vim / forget; gpt-4o-mini handles the same sequence correctly; cites logs/3A783293.jsonl). Full source: `report/weak_model_history_parroting.md`.

## E. Architecture overview (§1) — E1 DONE (via the §1 intro); E2–E5 still owed

- [x] E1. ✅ DONE — §1 "Introduction & System Overview" covers the Controller-wraps-LPU principle + the loop (`fig:architecture`) and context assembly (`fig:context_map`). *(Gap: the one-sentence "every feature = tool | context block | controller logic" framing rule isn't stated — add it if you want E1 airtight.)*
- [x] E2. ✅ DONE — §1 "The Tool Set": 8-tool inventory table (`tab:tools_overview`) up front, pointing to the full `TOOL_SCHEMAS` in Appendix A. Also reconciled the intro's "five universal tools" line → "core set grows to eight" (fixes the H4 wording flag).
- [x] E3. ✅ DONE — §1 "State Layout": `~/.doit/` state tree (sessions/, memories.json, shell_hist/, cd_target, logs/). Repo-structure listing was dropped as redundant (not required by assignment §319–338; duplicates the submitted code + architecture narrative). §1.3 (Context Assembly) prose also simplified.
- [ ] E4. §0: one paragraph on the logging infrastructure (raw LLM traffic in `logs/` as evidence) + where submitted logs live. *(Prose.)*
- [ ] E5. §1: state which system-prompt blocks exist at v1 and forward-reference how later phases only *add* context blocks. *(Prose.)*

## F. Limitations (per section) & Conclusion — PER-SECTION DONE (F1–F6b); F7 Conclusion still owed

The assignment requires **limitations for each section**. Add a short Limitations block where missing.
- [x] F1. ✅ DONE — change_dir section: cd silently no-ops if the shell snippet isn't installed (+ path checked at decision time). Added as a `\paragraph{Limitations.}`.
- [x] F2. ✅ DONE — §2 (dangerous commands): regex false positives (`grep "rm -rf" notes.txt`), blind spots (`$(...)`, `xargs rm`), prefix-based sudo/interactive detection (`ssh -p 2222 host`).
- [x] F3. ✅ DONE — §4 (multi-turn): K=10 window drops older turns entirely (compaction described-but-unimplemented); + DOIT_SESSION="default" fallback.
- [x] F4. ✅ DONE — §5 (clarifications): read-only empty-input default can surprise; Ctrl-C path only logged; MAX_CLARIFICATIONS=2 forces a guess.
- [x] F5. ✅ DONE — §10 (output awareness): head/tail truncation loses mid-output + prompt-injection surface (shell output is user-controlled text).
- [x] F6. ✅ DONE — §11 (multi-tasking): 24h recency filter; thin one-line summaries need `read_session` for faithful copying.
- [x] F6b. ✅ DONE — §3 (model flexibility: weakest-model bound, one-shot JSON retry, model quirks) and §12 (plans: budget exhaustion, one-shot retry, pipeline-masked failures, weak-model plan gating).
- [ ] F7. New final **Conclusion** section: synthesis with logged numbers (guard overrides, parse retries), 2–3 surprises, honest limits. Report currently has NO conclusion. *(Separate section, not a per-section limitation — still owed.)*

## G. Small mechanical fixes

- [ ] G1. Check for a figure caption collision / float placement issue once compiled (all figures use `[H]`; verify after first build).
- [x] G2. ✅ DONE — staged/hypothetical listings (§11 bracketed narration, §12 self-correction, §2 guard claim) replaced with real logs.
- [x] G3. ✅ DONE — every ACDL figure is immediately followed by its textual listing.

## H. Partner review notes (Yuval + Arbel)

### Title page & front matter
- [x] H1. ✅ DONE — architecture diagram removed from the cover (title page now text-only).
- [x] H2. ✅ DONE — diagram moved into new §1 "Introduction & System Overview" as `fig:architecture`, **with the added Controller→User arrow** ("Answer / Output" return path).
- [x] H3. ✅ DONE — `\tableofcontents` added after the title page.
- [x] H4. ✅ DONE — introduction added as §1, then corrected for accuracy/loyalty to the code: "five universal tools" → "core set grows to eight"; code-mapping fixed (`env.history` → `sys.history`) and completed to all 7 context blocks with the real `build_messages` splice order; `config.py` field list completed. Includes `fig:architecture` + `fig:context_map` + the E2 tool table + E3 layout listings.

### Section 1 (single command)
- [ ] H5. State the available tools at this stage (run_command, answer) in the §1 body. *(Prose — small.)*
- [ ] H6. Show/reference the §1 system prompt (now in Appendix A — add a short excerpt or pointer). *(Prose — small.)*
- [ ] H7. Make the model explicit in the §1 narrative (`openai/gpt-4o-mini`), not only in the decision box. *(Prose — small.)*
- [x] H8. ✅ DONE — §1/§5/§10 example listings fully neutralized: `README.md`→`notes.txt`, `DECISIONS.md`→`report.txt`, `acdl`→`photos`, `doit`→`backup.sh`; also fixed §7's `find -name "*.py"` output that wrongly showed `./doit` → `./train.py`. `grep` confirms zero `CLAUDE.md`/`DECISIONS.md`/`README.md` left in report.tex. (Done by name-swap, not a live re-run — the listings are illustrative; if you'd rather have genuine re-run output, that's H11.)
- [x] H9. ✅ DONE — §Single command now has a Limitations subsection (single-command cap can't chain; output not fed back / no meant-vs-said check; portability depends on the model). Every section (12/12) now has a Limitations block, per the assignment's per-section requirement.
- [x] H10a. ✅ DONE — v1 spec lists only `run_command, answer` (change_dir removed).
- [x] H10b. ✅ DONE — v1 annotates that native tools travel out-of-band via `tools=` (only the prompted adapter embeds them).
- [x] H10c. ✅ DONE — v1 shows ENV_INFO and user_request as two separate `U:` messages (matches `build_messages`).
- [ ] H11. Insert the real §1 logs (joke refusal C3, impossible-request C4, runs-from-anywhere C5) into §1. *(Overlaps H8 — do after neutral-dir re-run.)*
- [x] H12. ✅ DONE — §1 "Raw LPU Exchange (native tool-calling)": trimmed real request/response for the `ls -la` demo (real `tool_calls` id + `arguments` + usage numbers from `logs/phase1/llm_raw_p1demo.jsonl`).

### Section 2 (dangerous commands)
- [x] H13. ✅ DONE (report-wide) — stripped the `Design Decision:` prefix from all 17 decision-box titles (topic only now); the `\subsection{Design Decisions}` heading is the subtitle before each group. Fixed §4 (Model flexibility), where the adapter box sat under Implementation Details with no such heading — added a `Design Decisions` subtitle before it. The 2 limitation-decision boxes now read `Limitation: <topic>` under their `\subsection{Limitations}`. Verified: zero `Design Decision:` prefixes remain, every box has its subtitle.
- [x] H14. ✅ DONE — real guard-override example (`ls > files.txt`) + 6/15 tally added to §2.
- [x] H15. ✅ DONE (2026-08-10) — manually re-ran §2 safety flow LIVE on gpt-4o-mini/native, fresh session: destructive confirm/decline ✓, `>`-redirect guard gate ✓, `install htop` → clarify → declined (no sudo run) ✓, `open vim` → refused via `answer` ✓. NOTE found+fixed en route: `doit.cfg` was left on `ollama/gemma3:4b` (prompted) from the comparison work — switched back to `openai/gpt-4o-mini`/native. **Set doit.cfg to the intended default before submitting.**
- [x] H16. ✅ DONE — `acdl/v2_safety.acdl` AVAILABLE_TOOLS comment now spells out `run_command(command, is_destructive, explanation)` and notes those two are safety layer 1. Kept it in the COMMENT (not the rendered node), so `acdl_v2.png` does NOT need re-rendering. The `.acdl` listing in the report auto-updates via `\lstinputlisting`.

## Z. Before submission (final checklist)

- [ ] Z1. ⭐ **BEFORE SUBMIT (Yuval will add this):** include `tests/cases.md` (the ~60-case suite the models were run against) as an appendix so graders see exactly what was tested. Yuval is adding it as a report appendix himself — **do not forget to actually include it before submission.**
- [x] Z2. ✅ DONE — H8 complete: all repo-internal filenames swapped to generic ones (`notes.txt`/`report.txt`/`photos`/`backup.sh`/`train.py`); `grep` confirms none left. (If genuine re-run output is wanted instead of the name-swap, that's H11.)
- [x] Z3. ✅ DONE — see H15 (live safety re-run passed on gpt-4o-mini/native, fresh session).
- [ ] Z4. Compile the PDF (`cd report && pdflatex report.tex` ×2, or Overleaf) and fix any listing/UTF-8 errors.
- [ ] Z5. Check the course's **AI-assistance disclosure** policy and comply.
- [ ] Z6. Final read-through for the owed prose: §0 overview depth (E2/E3/E4 tables + trees), Conclusion (F7), D2/D4/D5 sentences. (Intro/H4 and per-section Limitations/F1–F6b now DONE — just re-read them for voice.)
- [ ] whenever a test case is mentioned in the report, add its exact description. the cases.md appendix is an appendix but people should understand the report without opening the appendixes:
4.6 Local-vs-Local Head-to-Head: qwen3 vs gemma3
The assignment asks specifically for a comparison between a local model adapted for tool-calling
(qwen3:4b-instruct, native) and one that is not (gemma3:4b, prompted JSON). They split the
wins — neither is uniformly better — and the differences land exactly where structured output
and tool-use decisions matter.
qwen wins (case 57, “3 most common words”). qwen composes a correct pipeline
and gets the right counts; gemma mis-flags the read-only pipeline as destructive and aborts,
answering nothing:
1 # qwen3 ( native ) -- correct
2 $ grep - oE ’ ([ a - z ]+) ’ notes . txt | sort | uniq -c | sort - nr | head -n 3
3 4 the
4 3 apple
12
Assignment 3: Agentic Shell (doit) Yuval Reuveni & Arbel Tepper
5 2 fox
6 # gemma3 ( prompted ) -- over - flags a read - only pipeline , aborts , answers
nothing
7 This command modifies the filesystem :
8 cat notes . txt > temp . txt && tr ... | sort | uniq -c | sort - nr |
head -3
9 Proceed ? [ y / N ] Aborted . ( Nothing was executed .)
