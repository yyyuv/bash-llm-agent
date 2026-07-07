# `doit` — The Elaborated Plan

Companion to `PLAN.md` (which stays the compact reference). This file explains **every part in plain language with examples**, and flags every **open decision** you two need to make before implementation. Decisions are marked `🔶 DECISION` — read the scenarios, pick, write your choice down. Once all decisions are made, implementation can run without stopping to think.

---

## Part 0: The big picture — what are we actually building?

`doit` is a program you run from your terminal. You type a request in English; it figures out what to do and does it:

```
> doit "list the files in my Documents folder"
ls ~/Documents          ← the command it decided to run
doc1.pdf  doc2.pdf      ← the command's output
```

Internally, every invocation does the same dance:

1. **Gather context** — who am I, where am I (cwd), what happened before, what does the user want now.
2. **Ask the LLM** — send that context, get back a *structured decision* ("run this command" / "answer with this text" / "ask the user this question").
3. **Execute the decision** — run the command / print the answer / prompt the user.
4. **Record what happened** — so the *next* invocation of `doit` knows about this one.

The course's Class 9 vocabulary for this: `doit` is an **LLM System** — a **Controller** (our Python code, which owns all logic and state) wrapping an **LPU** (the language model, which only ever sees text and emits structured instructions). The LLM never "does" anything. It only *suggests*. Our code decides whether and how to act. Keep this separation strict and every later section of the assignment becomes an add-on rather than a rewrite.

### Why "everything is a tool"

Instead of building each feature its own machinery, we give the LLM a fixed menu of 5 actions ("tools"), and every assignment requirement is served by one of them. When the LLM responds, it must pick exactly one tool per step.

### The tool table, explained

The column **"replaces assignment section"** in PLAN.md means: *this tool is the mechanism that implements that section of the assignment*. The assignment describes features as user-facing behaviors; we implement each behavior as a tool the LLM can call. Mapping:

**`run_command(command, is_destructive, explanation)`**
The workhorse. The LLM fills in:
- `command`: the actual shell string, e.g. `ls -lt ~/Documents`
- `is_destructive`: `true` if the command changes the filesystem/system state (creates, deletes, moves, writes), `false` if it only reads (ls, grep, cat, find, du…)
- `explanation`: one sentence describing what the command does, in plain language — shown to the user when confirmation is needed ("This will delete all .log files in the current directory").

This one tool covers assignment part 1 (translate & execute) and part 2 (dangerous command detection — via the flag). Example LLM decision for `doit "delete all log files here"`:

```json
{"tool": "run_command", "args": {
  "command": "rm ./*.log",
  "is_destructive": true,
  "explanation": "Deletes every file ending in .log in the current directory."}}
```

Our controller sees `is_destructive: true` → prints the command + explanation → waits for `y`.

**`answer(text)`**
The LLM just talks — no command executed. Covers three assignment requirements at once:
- "tell me a joke" → **polite refusal, staying in role**: "Sorry — I'm a shell command agent; I can't help with that. Ask me anything about your files or system." Our policy decision: `doit` doesn't do chit-chat, it declines nicely. This still satisfies the assignment's "respond nicely to such requests" (nicely ≠ compliantly), and we state the rationale in the report: a scoped agent is more predictable, and refusing off-domain requests is itself a design stance on agent behavior. The refusal text lives in the system prompt.
- "make my laptop fly" → answer explaining this isn't a shell task (assignment: impossible requests)
- "how do I find files larger than 1GB?" → answer with an explanation + example command *without running it* (assignment section "Richer interactions" — this IS in scope, it's shell-domain knowledge, not chit-chat)

`answer` is also the **finish** signal: when the LLM calls it, the agentic loop ends and `doit` exits. This mirrors Class 9's note that tool sets often include `finish(msg)`.

**`ask_user(question, options[])`**
The LLM is unsure and wants input before proceeding. Covers the "Clarifications" section:

```
> doit "list files in my home folder sorted by date"
Do you want to sort by:
  1. modification date
  2. creation date
> 1
-rw-r--r-- ...
```

Mechanically: controller prints the question, reads a line from stdin, appends the answer to the conversation, and calls the LLM again *within the same invocation*. The clarification is a loop iteration, not a new `doit` call.

**`remember(fact)` / `forget(id)`**
Writes/removes a persistent fact about the user in `~/.doit/memories.json`. Covers the "Memory" section. Example: `doit "move to ~/school/llms/ass3. this is my LLM class project folder."` → the LLM makes **two** tool calls in one turn: `change_dir(~/school/llms/ass3)` then `remember("~/school/llms/ass3 is the user's LLM class project folder")`. Next week, in a fresh terminal: `doit "go to my llm class project"` → the memory is in the context → the LLM knows the path.

**`change_dir(path)`**
Special-cased `cd` — see Part 0.5 below for why cd cannot just be a `run_command`.

### Why NOT a tool per shell command?

The assignment warns against implementing `ls`, `grep`, `git` as separate tools. Reason: the shell already *is* a universal composable tool — the LLM knows shell syntax from pretraining far better than it would learn 40 custom tool schemas. One `run_command` string gives it pipes, flags, globs, everything. Fewer tools also means the weak local model has fewer ways to get confused.

### The 5-tool decision schema is the ONLY contract

Whatever model we use (API, mistral, llama3), the controller only ever receives: *tool name + args*. This is the interface both of you code against, and the thing to freeze on day 1.

---

## Part 0.5: The `cd` trap — the one thing that will bite you if not understood

**The problem, concretely.** When you run `doit "go to my project folder"`, your terminal (bash) starts a *child process* (python running doit). In Linux, a child process can change *its own* working directory, but **can never change its parent's**. So even if our python code runs `os.chdir("/home/yuval/school")` and exits successfully — your terminal is still sitting in the old directory. Try it yourself:

```bash
python3 -c "import os; os.chdir('/tmp')"
pwd        # ← still your old directory. The chdir died with the child.
```

But the assignment *requires* `doit "go to my llm class project"` to actually move you there. Contradiction? No — trick.

**The trick.** We can't push a `cd` up into the parent shell, but the parent shell can *pull* one. We define `doit` in your `.bashrc` not as the program itself, but as a **shell function** wrapping it:

```bash
doit() {
  command doit "$@"                              # run the real python program
  local t=~/.doit/cd_target_$DOIT_SESSION        # did doit leave a note?
  [ -f "$t" ] && cd "$(cat "$t")" && rm "$t"     # if yes: THE SHELL ITSELF cds
}
```

Because a function runs *inside* your shell (not a child process), the `cd` in the last line works. Flow for `doit "go to my llm class project"`:

1. Python doit runs, LLM calls `change_dir("~/school/llms/ass3")`.
2. Python validates the path exists, writes it to `~/.doit/cd_target_<session>`, records the new cwd in session state, prints "ok", exits.
3. The shell function sees the note file → `cd ~/school/llms/ass3` → deletes the note.
4. You're there. The *next* `doit` call also reads cwd correctly since bash passes it down.

**Why record it in session state too?** So the agent's own history knows where it "is" even before the shell function fired, and so `doit` running in *another* terminal doesn't get confused (the note file is suffixed with the session id).

🔶 **DECISION 1 — how to handle cd.**
- **(a) The shell-function wrapper above.** Pro: the assignment's example actually works; shell hooks are explicitly allowed if documented; small and robust. Con: `doit` breaks (silently no-cd) if someone runs it without the bashrc snippet installed.
- **(b) Don't support real cd** — when asked to navigate, print `cd ~/school/llms/ass3` and tell the user to run it. Pro: zero shell integration. Con: fails the assignment's explicit example; weak grade on that section.
- **(c) `eval "$(doit ...)"` style** — doit prints shell code, user always invokes through eval. Pro: classic unix pattern. Con: awkward UX, dangerous (everything doit prints becomes executable), hard to also print normal output.
✅ **RESOLVED: (a)** — the shell-function wrapper. Mitigate the con: if `doit` detects the snippet isn't installed (no `DOIT_SESSION` env var), it prints a one-time warning with install instructions instead of failing silently.

---

## Part 0.6: State — everything under `~/.doit/`

`doit` is a *process that dies after every request*. All continuity lives on disk:

```
~/.doit/
├── sessions/<session_id>.jsonl   # per-TERMINAL conversation history
├── memories.json                 # persistent user facts (cross-everything)
├── shell_hist/<session_id>       # what the USER typed manually (from a bash hook)
├── cd_target_<session_id>        # the cd "note", transient
└── logs/                         # full raw LLM traffic, for the report & debugging
```

One `sessions/*.jsonl` record = one turn:

```json
{"ts": 1730000000, "cwd": "/home/yuval/school/llms/ass3",
 "request": "list the files",
 "steps": [{"tool": "run_command",
            "args": {"command": "ls -la", "is_destructive": false},
            "stdout": "...(truncated)", "stderr": "", "returncode": 0}],
 "final_answer": null}
```

Why JSONL (one JSON object per line): appending is atomic-ish and trivial, reading the last K turns is `tail`-simple, and each line is a self-contained record.

🔶 **DECISION 2 — storage format.**
- **(a) JSONL files** as above. Pro: dead simple, human-readable (great when debugging and when writing the report), no dependencies. Con: cross-session queries ("what happened in other terminals recently?") mean globbing and reading several files.
- **(b) SQLite** single DB, tables sessions/turns/memories. Pro: real queries, one file, concurrent-write safe. Con: more code, less greppable, overkill at this scale.
✅ **RESOLVED: (a)** — JSONL.

---

## Part 0.7: Phase dependency map & who builds what

Phases and what each *requires* from previous ones:

```
Phase 0  skeleton, config, PATH, LiteLLM hello-world
   └─► Phase 1  single command (tools: run_command, answer; max_steps=1)
          ├─► Phase 2  safety (is_destructive flag + regex guard + confirm)
          └─► Phase 3  3 models via two adapters   ◄── riskiest, do EARLY
                 └─► Phase 4  multi-turn (session history in context)
                        ├─► Phase 5  clarifications (ask_user) + richer interactions
                        ├─► Phase 6  memory (remember/forget)
                        └─► Phase 7  user awareness (shell history hook)
                               └─► Phase 8  multi-tasking (per-session streams)
                                      └─► Phase 9  extension
ACDL + logged tests: gate at the END of EVERY phase, not at the end of the project.
```

Phases 5, 6, 7 are mutually independent — perfect for parallel work once Phase 4 lands.

**Split in a nutshell** (details in the previous discussion):
- **Student A — engine**: Phases 0, 2, 3 + shell integration (bashrc, session ids, cd wrapper, history hook) + runs the 3-model comparison. Testable with a *mocked LLM*.
- **Student B — brain**: context assembly, controller loop, Phases 4, 5, 6 + ACDL specs + test scenarios & curated logs. Testable with a *mocked shell*.
- **Together**: Phase 1 (pair-program it — it defines the contracts), Phases 7–9, report.

Since Claude writes most code, "owning" a phase means: prompting/reviewing/running/fixing that phase, writing its ACDL and design notes yourself, and being able to defend it.

---

# The plan, section by section (following the assignment's order)

Each section: what the assignment demands → how it works in our design → concrete examples → open decisions.

---

## Section 1 — Single command at a time (Phase 0 + 1)

**Assignment demands:** `doit "instruction"` → print the shell command → execute → print output. Must be python, no file extension, on PATH, works from any directory. Must handle: impossible requests, and chit-chat ("tell me a joke") nicely. The hint in the assignment ("separate the model's response from the execution step... recognize which case it got") is *exactly* our tool schema: `run_command` vs `answer` are the cases.

**How it works here:**
- `doit` file: starts with `#!/usr/bin/env python3`, `chmod +x doit`, symlinked into `~/.local/bin` (on PATH). Despite no extension, it just imports our package and calls `main()`.
- `~/doit.cfg` read at startup: which model, api keys/base urls, max_steps, temperature (use 0 — we want deterministic commands, not creative ones).
- Phase 1 controller is the degenerate loop: build context → one LLM call → if `run_command`: print command, run it via the assignment's `subprocess.run` snippet, print stdout/stderr; if `answer`: print text. Done.
- Execution details that matter: capture stdout+stderr+returncode always; `timeout=20` and catch `TimeoutExpired` ("command timed out after 20s"); nonzero returncode is not a crash — print stderr, record it (later sections let the user ask "why did that fail?").

**Example transcripts to target (also our first test cases):**

```
> doit "show me the 5 biggest files here"
du -ah . | sort -rh | head -5
1.2G  ./data/dump.bin
...

> doit "make my computer quieter"
I can't control fan speed reliably from a shell command — that's usually
firmware/BIOS-controlled. I can show CPU-heavy processes instead if you like.

> doit "tell me a joke"
Sorry — I'm a shell command agent, so no jokes from me. I can help with
anything involving your files, folders, or system though.
```

🔶 **DECISION 3 — bash or zsh? → RESOLVED: support both, auto-detect.** One partner is on Linux/bash, one on macOS/zsh, so we normalize at the boundary: `doit` reads `$SHELL` (overridable via `shell =` in `doit.cfg`) and uses it as subprocess `executable=`. Context tells the LLM `env.shell_type` + `env.os` (macOS = BSD userland: no `find -printf`, different `stat`/`ls` flags) and asks for POSIX-portable syntax. Two hook snippets — `shell/bashrc_snippet.sh` (PROMPT_COMMAND, `history 1`) and `shell/zshrc_snippet.sh` (`precmd()`, `fc -ln -1`) — write the **identical** `ts|cwd|cmd` format to `~/.doit/shell_hist/`, so everything past the snippets is shell-agnostic. The `doit()` cd-wrapper is byte-identical in both. A small `shell/install.sh` detects `$SHELL` and installs the right snippet (on macOS-bash it also makes `.bash_profile` source `.bashrc`). Test the suite on both machines; document both snippets in the report.

🔶 **DECISION 4 — API provider.** Needed before Phase 0 ends.
- **(a) Gemini flash (free tier)**: costs nothing; good tool-calling; LiteLLM string `gemini/gemini-2.0-flash`. Con: rate limits on free tier can annoy during heavy testing.
- **(b) OpenAI gpt-4o-mini**: a few dollars for the whole assignment, very reliable structured output, the most-tested path in LiteLLM. Con: needs a paid key.
- **(c) Anthropic claude-haiku**: same trade-off as (b).
✅ **RESOLVED: (b) OpenAI** — paid key already available. Use `openai/gpt-4o-mini` (cheap, reliable tool-calling); key via `OPENAI_API_KEY` env var, never in `doit.cfg` or the repo.

---

## Section 2 — Identifying dangerous commands (Phase 2)

**Assignment demands:** read-only commands run immediately; filesystem-modifying commands are shown + explained + require `y`.

**How the danger is identified — two layers (defense in depth):**

*Layer 1 — the LLM's own flag.* `is_destructive` is a required argument of `run_command`. The model classifies the command it just wrote, in the same response. The assignment suggests "a separate LLM call" as one option; see the decision box for why we deviate (and we'll justify it in the report — graders like reasoned deviations).

*Layer 2 — a deterministic Python guard.* Never trust a model (especially a 7B one) alone with `rm -rf`. Before executing anything the model marked `is_destructive: false`, our code scans the command for write-indicating patterns: `rm, mv, cp, mkdir, touch, chmod, chown, dd, ln, tee, sed -i, truncate, > , >>, git commit/push/reset/clean, curl|sh, sudo, find -delete, xargs rm...`. If the guard trips while the model said "safe" → we treat it as destructive anyway, and log the override (these logs become a report table: "N times the guard corrected the model").

**Sneaky cases to test deliberately** (great report material): `ls > files.txt` (redirect makes a "read" command write), `cat a.txt | tee b.txt`, `find . -name "*.tmp" -delete`, `echo hi $(rm -rf /tmp/x)` (command substitution). Also policy calls our code enforces regardless of the model: **never run sudo**; detect interactive commands (`vim`, `nano`, `top`, `less` without pipe) and respond via `answer` ("this opens an interactive program — run it yourself") since our subprocess capture would hang on them.

**Confirmation UX:**

```
> doit "clean up all the .tmp files under this folder"
⚠ This command modifies the filesystem:
    find . -name '*.tmp' -delete
  It permanently deletes every .tmp file under the current directory (no trash).
Proceed? [y/N] n
Aborted. (Nothing was executed.)
```

The abort is *recorded in session history* — so a follow-up `doit "ok actually do it"` works naturally in Phase 4.

🔶 **DECISION 5 — safety classification mechanism.**
- **(a) In-band flag + regex guard (as above).** Pro: zero extra latency/cost; identical mechanism across all 3 models; the deterministic layer catches model mistakes. Con: the model classifies its *own* output (mild conflict of interest); deviates from the assignment's hinted "separate call".
- **(b) Separate LLM classifier call** ("Is this command destructive? yes/no") after generation. Pro: matches the assignment's hint; independent judgment; a second model could even be used. Con: doubles latency and cost on *every* command; the weak local model may be a bad classifier anyway, so you still want the regex layer — at which point (b) adds little over (a).
- **(c) Regex/static analysis only, no LLM involvement.** Pro: fully deterministic. Con: no explanations; false positives (e.g. `grep "rm -rf" notes.txt` contains "rm -rf" but is read-only) unless the parser is smart; misses obfuscated writes.
✅ **RESOLVED: (a) to start** — in-band flag + regex guard. If testing shows the flag is unreliable (track it: every guard override is logged), we add (b) as a separate judge call. Either way this evolution is documented in the report — "started with X, measured, then Y" is exactly the design narrative graders reward.

---

## Section 3 — Model flexibility (Phase 3) ⚠ riskiest phase, schedule it early

**Assignment demands:** the same program works with (1) an API model, (2) a local model *with* tool-calling support, (3) a local model *without* it. Model chosen via `~/doit.cfg`. Must use LiteLLM. Your hardware is strong → the 7–8B tier: **mistral:7b** (tool-calling) and **llama3:8b** (plain instruct).

**Setup:** install Ollama, `ollama pull mistral:7b llama3:8b`. LiteLLM strings: `ollama/mistral:7b`, `ollama/llama3:8b`. Config decides everything:

```ini
[model]
name = ollama/mistral:7b
adapter = native        ; or "prompted"
```

**The two adapters — the heart of this section.** The controller calls `llm.call(context, tools)` and gets back a `Decision(tool_name, args)`. *How* that happens differs:

*Native adapter* (API model, mistral): we pass tool schemas through LiteLLM's `tools=` parameter; the provider/model emits a structured `tool_calls` object; we parse it directly. The model was *trained* to emit this format, so it rarely breaks.

*Prompted adapter* (llama3): the model has no tool-calling training, so we do it "by hand" — the system prompt contains the tool descriptions and an instruction like:

```
You must reply with ONLY a JSON object, no other text:
{"tool": "<run_command|answer|ask_user|remember|change_dir>", "args": {...}}
```

…and then we defensively parse whatever comes back: strip ```json fences, extract the first balanced `{...}`, validate tool name and args against the schema. **When parsing fails** (it will — this is expected and is literally part of what the assignment wants you to experience), we retry once, appending the parse error to the conversation: *"Your last reply was not valid JSON: <error>. Reply with only the JSON object."* If the retry also fails → graceful error to the user + full log saved (report gold).

**Same behavior, different plumbing** — the controller, safety layer, history, everything else is byte-identical across models. That's the architectural point to make in the report.

**What you'll observe (and should write up):** llama3 wrapping JSON in prose ("Sure! Here's the JSON: ..."), inventing tool names (`execute_shell`), forgetting `is_destructive`, over-triggering `ask_user`. Each observed failure mode + how the system coped = one paragraph of the required model-comparison chapter.

🔶 **DECISION 6 — prompted format: JSON or XML-ish tags?**
- **(a) JSON** as above. Pro: matches native tool-call format so both adapters share validation code; json.loads is strict (good for catching garbage). Con: 8B models sometimes mangle quotes/braces.
- **(b) Tags**, e.g. `<tool>run_command</tool><command>ls</command>`. Pro: some models emit tags more reliably than JSON; regex-parseable even when slightly malformed. Con: two parsing stacks to maintain; harder to validate nested args.
✅ **RESOLVED: (a) JSON.** If llama3's JSON failure rate turns out unbearable in practice, that discovery itself is report material, and (b) becomes a documented experiment.

---

## Section 4 — ACDL documentation (continuous, every phase)

**Assignment demands:** document the context sent to the LLM using ACDL, *while working*, for *each version*; report includes textual ACDL + generated visuals + the concrete prompt templates. It's an explicit grading pillar.

**Working procedure (the phase gate):** a phase is "done" only when `acdl/vN_<name>.acdl` exists, renders in the [live editor](https://acdlang26.github.io/acdlsite/visualizer.html), a screenshot is saved, and 2–3 test transcripts are logged. 30–45 minutes per phase; skipping this is the single most common way to lose easy points.

**Why our code makes ACDL almost mechanical:** `context.py` builds the message list from small named functions — `memories_block()`, `session_history_block()`, `user_shell_history_block()`... Each function = one ACDL element (`sys.memories`, the history `ForEach`, `USER_SHELL_HISTORY`). The report can literally show a two-column mapping: ACDL element ↔ function name. That's the "compare report ↔ code behavior" property the grading text asks for, handed to the grader on a plate.

**Vocabulary check** (from the syntax reference — using it correctly is graded detail): `@T` = current turn (each doit invocation = a turn, per the assignment), `@T.I` = current step inside the turn (tool-loop iterations), `S:/U:/A:/T:` roles, `env.*` = external world (cwd, user request, shell history), `sys.*` = agent state (memories, tool configs, past actions), `resp.*` = prior model outputs, `ALL_CAPS` = prose templates whose text lives in `prompts/`, `camelCase()` = computed functions like `summarize(...)`, `truncate(...)`.

Full final-version ACDL sketch is in PLAN.md §4. Per-phase, v1 is tiny (S: instructions+tools, U: env.cwd + request) and each phase adds one block — the *sequence* of specs visually tells your build story, which is exactly what the report needs.

Also write a **second spec for the prompted adapter** (tools as text in `S:`, tool results as `U:` instead of `T:`) — the two renderings side by side is the best figure in your model-comparison chapter.

---

---

# ⏸ SECTIONS BELOW: NOT YET REVIEWED TOGETHER

**Current planning scope ends here (through Section 4 / Phase 3).** Sections 5–12 below are drafted but pending joint review — decisions 7–11 stay open until then. Do not start Phase 4+ before that discussion.

---

## Section 5 — Multi-turn (Phase 4)

**Assignment demands:** `doit "list the files..."` then `doit "now sort them by date"` then `doit "no, i meant latest first"` — each a *separate process*, yet they chain. State must persist between invocations (they suggest a hidden home folder — our `~/.doit/`).

**The three sub-problems and our answers:**

*Where is history stored?* `~/.doit/sessions/<session_id>.jsonl` (Part 0.6). Each turn appends one record after completion.

*How is it shown to the LLM?* Replayed as proper chat messages, because models are trained on chat format and handle it far better than a text dump. Turn t becomes: `U:` the request → `A:` the tool call made → `T:`/`U:` the (truncated) output → `A:` final answer. Last K turns only (K≈10) — older turns are dropped for now (Phase 9 extension #2 would summarize them instead).

*New command vs. reference to a previous one?* **We don't classify — the LLM does, implicitly.** With history in context, "now sort them by date" naturally reads as a follow-up; a fresh "show disk usage" naturally doesn't. No brittle "is this a follow-up?" classifier. Trust context; test it.

**Output truncation policy** (matters here and in Section 9): outputs enter history truncated — first ~3KB + last ~1KB + a marker `[... 1,842 lines omitted ...]`. Full output saved to `logs/`. Head+tail because errors usually print at the end and listings at the start.

**Target transcript:**

```
> doit "list the files in my Documents folder"
ls ~/Documents
report.pdf  notes.txt  old_draft.pdf
> doit "now sort them by date"
ls -lt ~/Documents
...
> doit "no, i meant latest first"          ← model realizes -lt already IS latest-first,
Already sorted latest-first — the top entry (report.pdf) is the newest.   ← so it answers instead of blindly rerunning. Chef's kiss if it does this.
> doit "i meant creation date"
ls -lc --sort=time ~/Documents             ← Linux caveat: true creation time (crtime)
...                                          isn't exposed by ls; -c shows ctime. The
                                             model should say so — good clarify trigger!
```

🔶 **DECISION 7 — how much of the command output goes into history context?**
- **(a) Truncated real output (head+tail, as above).** Pro: follow-ups like "which of these is safe to delete?" (Section 9!) need the actual output; simple. Con: burns context tokens, especially painful for the 7–8B local models with smaller effective context.
- **(b) Only metadata** (command, returncode, first 3 lines). Pro: tiny context. Con: kills Section 9 (output awareness) — the model can't discuss output it can't see; you'd need a "fetch full output" tool, adding complexity.
- **(c) Adaptive (metadata cliff)**: full output for the most recent turn, metadata-only for older ones. Pro: best of both. Con: the cliff — an older turn's output becomes undiscussable, so a follow-up two turns later that refers back to it ("delete the ones from the *first* listing") has nothing to see.
- **(d) Adaptive with tiered truncation — CHOSEN.** Two byte budgets instead of a metadata cliff: the *current/most-recent* turn keeps a rich truncated output (head ~3KB + tail ~1KB); *older* turns keep a compressed truncated output (head ~1KB + tail ~0.3KB) — still head+tail real content, just tighter. Pro: every past turn stays discussable (Section 9 works even for older outputs), while the 10× history multiplier is kept cheap; no "fetch full output" tool needed. Con: two constants instead of one, marginally more code than (c).
Decision: **(d)**. Rationale (2026-07-07): the metadata-only floor in (c) kills output-awareness for anything but the last turn; tiered truncation preserves the gist of older outputs (a listing's start + any trailing error) at ~3K tokens for 10 turns, versus ~10K for uniform 4KB. Full untruncated output always remains on disk in `logs/`.

---

## Section 6 — Clarifications (Phase 5)

**Assignment demands:** ask the user when unsure, wait for the answer, continue. Explicit worry: "useful but not annoying, asking only when needed". Also: what if the user doesn't answer?

**Mechanism:** the `ask_user` tool + the loop. When the model calls it, the controller prints the question (+ numbered options if provided), blocks on `input()`, appends the reply as a `U:` message, re-calls the model — all within the same doit process. Multiple clarifications per turn are possible (cap at 2 to enforce non-annoyance structurally, not just via prompt).

**The "not annoying" policy lives in the system prompt** — and is a real prompt-engineering deliverable. Our rule of thumb, stated to the model: *ask only if (a) the ambiguity would change which files get touched by a destructive action, or (b) reasonable interpretations lead to materially different results AND no interpretation is clearly dominant. Otherwise pick the most common interpretation and state your assumption in the output.* Example of the "state assumption" pattern (usually better than asking):

```
> doit "sort the files by date"
ls -lt        (sorting by modification date — say "creation date" if you meant that)
```

That parenthetical costs the user nothing; a blocking question costs a context switch. This trade-off discussion belongs in the report.

✅ **DECISION 8 — unanswered questions — CHOSEN: (a)** empty input → proceed with the stated default, combined with the destructive-vs-read-only split (destructive → abort, read-only → default); no timeout. (Not yet implemented — lands in Phase 5.) User presses Enter on empty input / hits Ctrl-C / walks away:
- **(a) Empty input → proceed with the stated default** ("no answer — using modification date"). Pro: flows nicely; the default was already communicated. Con: for anything destructive this is dangerous — so combine: destructive → abort, read-only → default.
- **(b) Empty input → abort the turn** ("cancelled; run doit again when you've decided"). Pro: maximally safe, simple. Con: annoying for harmless cases.
- **(c) Add a timeout** (e.g. 60s → treat as (a)/(b)). Pro: handles walk-aways. Con: `input()` with timeout is fiddly (signals/select); little value for a CLI you're actively typing into.
Recommendation: (a) with the destructive-vs-readonly split, no timeout. Whatever you choose, log it and mention the edge in the report.

---

## Section 7 — Richer interactions (Phase 5, same code)

**Assignment demands:** "how do I do X" questions answered *without executing*; follow-ups like "modify it to do y" and then "execute it" must work, each as a new doit invocation.

**Why we get this nearly free:** `answer` already exists, and Phase 4 already persists answers into history. The chain works because each turn sees the previous ones:

```
> doit "how do i find all python files modified in the last week?"
Use:  find . -name '*.py' -mtime -7
(-mtime -7 = modified within 7 days. Not executed — just the recipe.)
> doit "modify it to also show file sizes"
find . -name '*.py' -mtime -7 -exec ls -lh {} +
> doit "execute it"
find . -name '*.py' -mtime -7 -exec ls -lh {} +
./doitlib/tools.py  4.2K
...
```

Turn 3 is the interesting one: the model must lift a command *out of its own previous answer* and pass it to `run_command` (with the safety flag!). This is a distinct capability — put it in the test suite for all three models; the weak model fumbling it ("execute what?") is prime comparison material.

**"What can happen in longer sequences"** (the assignment prompts you to think): drift (by turn 8, is "it" still the find command or the ls from turn 5?), context growth, and the model confusing *discussed* commands with *executed* ones. Mitigation for the last: history records mark executed commands distinctly from answered text. Note these in the report's limitations chapter with a real transcript.

---

## Section 8 — Memory (Phase 6)

**Assignment demands:** persistent cross-session memories, stored *upon request* (explicitly or implied); one command may trigger both an action AND a memory store; memories can later be *changed* ("I changed my mind about the sorting order — ask me each time").

**When are memories stored?** The model decides, guided by the system prompt: store when the user states a stable fact/preference about themselves or their environment ("this is my project folder", "I prefer creation date", "always use eza instead of ls"). *Not* for transient facts ("I'm looking for a file from yesterday"). The dual-trigger case works because the loop allows several tool calls per turn: `change_dir(...)` then `remember(...)` then `answer("ok")`.

**How do memories appear in context?** All of them, every invocation, in a labeled system block:

```
Known facts about the user (persistent memory):
- [m3] ~/school/llms/ass3 is the user's LLM class project folder
- [m5] user prefers ls sorted by creation date by default
```

The visible `[id]`s are what make **editing** work: "I changed my mind about the sorting order, ask me each time" → model sees m5 in context → calls `forget(m5)` + `remember("ask each time which sort order to use")`. Without visible ids, the model can't reference what to delete.

🔶 **DECISION 9 — inject all memories always, or filter by relevance?**
- **(a) All memories, always.** Pro: trivial; nothing relevant is ever missing; at your scale (dozens of memories max) token cost is negligible. Con: doesn't scale to hundreds; irrelevant memories can occasionally distract a small model.
- **(b) Relevance filtering** (embed memories, retrieve top-k per request). Pro: scales; impressive-sounding. Con: real complexity (embedding model, index), new failure mode (the *needed* memory doesn't get retrieved — worse than distraction), hard to debug.
Recommendation: (a), with (b) described as future work — OR as one of your three extension *descriptions* (free content for Phase 9!).

---

## Section 9 — User awareness + Output awareness (Phase 7)

**Assignment demands (user awareness):** know what the *user* did manually in the shell — e.g. after the user hand-runs `cd`, `mkdir data`, `python train.py`, then `doit "summarize what I just did"` must work, distinguishing user-run from doit-run commands. Shell hooks / bashrc changes allowed if documented.

**Mechanism — the PROMPT_COMMAND hook.** Bash runs `$PROMPT_COMMAND` before every prompt. Our snippet appends the last command + timestamp + cwd to a per-session file:

```bash
export PROMPT_COMMAND='echo "$(date +%s)|$(pwd)|$(history 1 | sed "s/^ *[0-9]* *//")" >> ~/.doit/shell_hist/$DOIT_SESSION'
```

After the user types three commands, `~/.doit/shell_hist/abc123` holds:

```
1730001000|/home/yuval|cd ~/school/llms/ass3
1730001005|/home/yuval/school/llms/ass3|mkdir data
1730001010|/home/yuval/school/llms/ass3|python train.py
```

**Distinguishing user vs doit commands:** two independent signals — (1) doit's own commands are recorded in `sessions/*.jsonl`, so anything in shell_hist matching a recent doit command is doit's; (2) simpler and near-sufficient: the shell_hist lines where the command starts with `doit ` are invocations, everything else is the user. Context gets a clearly labeled block (labeling is the actual answer to the assignment's "how to integrate both behaviors" question — the model just needs unambiguous provenance):

```
Commands the USER ran manually in this terminal (most recent last):
  [in /home/yuval] cd ~/school/llms/ass3
  [in .../ass3]    mkdir data
  [in .../ass3]    python train.py
```

**Also solved by this hook: knowing the real cwd.** The user may have manually `cd`-ed since doit last ran; the newest shell_hist line's cwd field tells us where we are — plus python's own `os.getcwd()` (doit inherits the shell's cwd at launch) as ground truth.

**Output awareness** — mostly already done by Decision 7(c): the last turn's full-ish output is in context, so `doit "which of these looks safe to delete?"` after a listing, or `doit "why did that command fail?"` after a stderr, just work — the model reads the recorded output/stderr and either answers directly or runs a follow-up command (e.g. `file suspicious.bin` to inspect before recommending deletion). Test both paths explicitly.

⚠ Worth one line in the report's limitations: shell output entering the LLM context is an *injection surface* — a file named `ignore previous instructions.txt` appearing in an `ls` output is user-controlled text flowing into the prompt. Acknowledging this = maturity points.

---

## Section 10 — Multi-tasking (Phase 8)

**Assignment demands:** two terminals, interleaved doit usage; "sort them by date" in window 1 must refer to window 1's listing even though window 2 did things more recently; but "do the same folder task we did in window 2" must reach *across*.

**Why this is nearly free for us:** since Phase 0, every terminal has its own `DOIT_SESSION` id (set in bashrc: `export DOIT_SESSION="${DOIT_SESSION:-$(uuidgen | cut -c1-8)}"` — the `:-` keeps it stable across re-sourcing), and *all* state files are keyed by it. Window 1 and window 2 have physically separate histories. "Sort them by date" in window 1 sees only window 1's history → refers to the listing. Correct behavior falls out of the file layout.

**The cross-reference case** needs the opposite: context must include *awareness* of other sessions without *drowning* in them. Our approach: this session's history in full detail + one-line summaries of other recently-active sessions:

```
Other active terminal sessions (summaries):
- session f4a2 (5 min ago, in ~/Documents): created folders 2020..2026
```

"Do the same folder task we did in window 2" → the summary is in context → the model recreates the task here. If the summary is too thin, the model can be given a `read_session(id)` tool — see the decision.

🔶 **DECISION 10 — cross-session awareness mechanism.**
- **(a) Always-injected one-line summaries** of other recent sessions (as above). Pro: simple, no new tools; explicit cross-references usually carry enough info ("the folder task"). Con: summaries may lack the detail needed to actually redo a task (which years? 2020–2026); stale summaries pollute context.
- **(b) A `read_session(session_id)` tool** — inject only session ids + timestamps + cwd; the model fetches full detail on demand. Pro: precise, scalable, genuinely agentic (a real multi-step retrieval!); minimal baseline context. Con: the weak model may never think to call it; two-step flows are exactly where 8B models stumble.
- **(c) Both**: summaries always + fetch tool for detail. Pro: robust for all models. Con: most code.
Recommendation: (c) if you implement extension #1 (multi-step) — the fetch tool then doubles as a showcase; otherwise (a).
Note: how summaries are produced (an LLM `summarize()` call per turn vs. cheap heuristic "request + last command") is a sub-choice; start heuristic, upgrade if quality demands.

**Test exactly the assignment's scenario** with two real terminal windows, and put both transcripts in the report — the grading text singles out multi-terminal handling as a differentiator.

---

## Section 11 — Further extensions (Phase 9)

**Assignment demands:** describe three, implement one; must be a real *agentic* capability; report must justify the choice and show an interaction where it matters.

**Our three (all sketched earlier, consolidated here):**

1. **Multi-step execution with command plans** *(recommended implementation)*. One request → sequence of commands with the output of each feeding the next, plan announced upfront, failures recovered. Why it's the right pick: (i) the controller loop *already* supports multiple steps — we mostly raise `max_steps` for command chains and add a plan-preview + confirmation when any step is destructive; (ii) it maps to Class 9's "dynamic multi-step" — the intellectually central concept of the course unit; (iii) it composes with everything else (a plan can include an `ask_user` mid-way). Showcase interaction to build the report around:

```
> doit "find the 3 largest log files anywhere under ~/projects and compress them"
Plan: 1) find the 3 largest .log files under ~/projects
      2) show them to you   3) gzip each (destructive → will confirm)
[1] find ~/projects -name '*.log' -printf '%s %p\n' | sort -rn | head -3
    812M /home/yuval/projects/train/run3.log ...
[2] These are the 3 largest. Compress all? [y/N] y
[3] gzip run3.log ... done — freed 790M total.
```

   And the *recovery* case (equally important for the report): step 1 returns nothing → model doesn't plow on, it reports "no .log files found — did you mean *.txt logs?".

2. **Context compaction** — when a session exceeds K turns, a separate LLM call summarizes turns 1..K-5 into a paragraph stored in the session file; context = summary + recent turns verbatim. ACDL-wise it's literally `summarize(prompt.History[@t])` — a beautiful spec. (If Decision 9(b) tempted you, this is the safer sibling.)

3. **Project profiles** — a `.doit.md` file per project directory (the agent.md idea from the assignment's own examples): "this is a python project; venv is ./venv; never touch data/raw". When cwd is inside the project, the file is auto-injected into context. Cheap to describe richly.

🔶 **DECISION 11 — which to implement.** Recommendation is #1, but if the multi-step loop feels risky with the local models (valid concern — 8B models are weakest exactly at multi-step), #3 is the lowest-risk high-value alternative. Decide after Phase 3, when you've seen the local models' competence firsthand.

---

## Section 12 — Report & testing discipline (Phase 10, fed by every phase)

Not elaborated here — PLAN.md §5–6 covers the skeleton. The three rules that matter:

1. **The logger runs from day 1.** Every LLM request/response and every executed command is auto-saved. Report-worthy transcripts are *found*, not staged.
2. **The fixed test suite (~15 cases) runs after every phase on the current model, and on all three models at Phases 3, 8, 9.** Failures are content, not setbacks — the assignment explicitly asks for failure/recovery logs and a weak-vs-strong model discussion.
3. **Per-phase, before moving on:** ACDL spec + screenshot, 2–3 transcripts, and a 5-line design-decision note in `DECISIONS.md` *written by you, not Claude* — it becomes the report's backbone and your oral-defense insurance.

---

## Decision checklist (fill in, then we implement)

| # | Decision | Options | Our pick |
|---|----------|---------|----------|
| 1 | cd handling | wrapper / no-cd / eval | ✅ (a) shell-function wrapper + missing-snippet warning |
| 2 | Storage | JSONL / SQLite | ✅ (a) JSONL |
| 3 | Shell | ~~bash / zsh~~ | ✅ both, auto-detect via $SHELL |
| 4 | API provider | Gemini / OpenAI / Anthropic | ✅ OpenAI (paid key available), gpt-4o-mini |
| 5 | Safety mechanism | in-band flag+guard / separate call / static only | ✅ (a) start; add judge call if flag proves unreliable |
| 6 | Prompted format | JSON / tags | ✅ (a) JSON |
| — | Chit-chat policy | comply / polite refusal | ✅ polite in-role refusal ("I'm a shell command agent") |
| 7 | Output in history | truncated / metadata / adaptive | ⏸ deferred — discuss before Phase 4 |
| 8 | Unanswered clarification | default / abort / timeout | ✅ (a) empty input → stated default, with destructive→abort / read-only→default split; no timeout |
| 9 | Memory injection | all / filtered | ⏸ deferred |
| 10 | Cross-session | summaries / fetch tool / both | ⏸ deferred |
| 11 | Extension | multi-step / compaction / profiles | ⏸ deferred (after Phase 3 anyway) |
