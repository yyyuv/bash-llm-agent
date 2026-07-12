## Output awareness via a follow-up command (§9, REPORT_TODO C9)

**What we set out to show.** §9 claims `doit` acts on the output of earlier
commands. Every prior log only showed the *weak* version: read some output, then
`answer`. C9 needed the *strong* version — a question the model **cannot** answer
from what it already sees, so it runs **another** command (`file`/`du`) to find
out first. We built a neutral sandbox with deliberately uninformative filenames
(`backup.tmp`, `cache.bin`, `core`, `data`, `notes`, `output`; sizes 2 B–3 MB) so
"which is safe to delete?" genuinely rewards inspection over guessing.

Model: `openai/gpt-4o-mini` (native adapter), real zsh session, 2026-07-12.
Full transcript: `logs/phase9/live_output_awareness_followup_gpt4omini.txt`.

**Result — the behavior fires.** Asked "which of these is safe to delete?", the
model ran a command instead of guessing:

```
$ doit "which of these files look safe to delete? check their types and sizes if you're unsure"
$ file backup.tmp                              ← ran a follow-up command, did not answer blind
backup.tmp: data
```

**Bonus — the Phase 9 `plan` tool genuinely lifts `max_steps=1`.** Plain phrasing
never triggered `plan` (one command suffices — correct). Explicit multi-step
phrasing did, and the session jsonl confirms **three `run_command`s executed in a
single turn** despite single-command mode, each command's real output feeding the
next:

```
$ doit "use a plan to list all files, sort them and investigate them to decide which is the safest to delete"
Plan:
  1. list all files in the current directory
  2. sort the files by size
  3. check the types and sizes of the files to determine which are safe to delete
$ ls -l          ← turn tools = [plan, run_command, run_command, run_command, answer]
$ ls -lS
$ file backup.tmp cache.bin core data notes output
```

A second run composed `plan` + `ask_user` + `answer` in one turn.

**Two honest limitations.**
1. *Single-command batching is non-deterministic.* With plans off, the model
   sometimes inspected **one file per turn** and never concluded on its own — it
   even lost track of its own progress ("No, I have not checked all files yet")
   and needed an explicit "do them all at once" nudge before emitting `file *`.
2. *Gathering facts ≠ good judgment.* Across every run the delete verdict was
   inconsistent and reasoned purely from `file` type + byte size ("big data files
   = keep, small text = delete"), ignoring the obvious name cues — `backup.tmp`
   and `cache.bin` are literally the disposable junk. Running the right
   inspection command does not guarantee the right conclusion.

**Lesson.** Output awareness is real and demonstrable, and the `plan` tool
provably escapes the single-command floor when a task warrants it — but in
single-command mode *whether* the model batches its inspection is non-deterministic,
and a correct information-gathering step can still be followed by a weak judgment.
