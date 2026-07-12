## The "how do I…" repeat / history-bleed bug (Phase 5, cases 29–31)

A follow-up conversation exposed a subtle prompt-rule conflict where prior turns "bled" into how a later, identically-worded turn was handled. Turn 1, a literal question, was correctly *answered* (not executed); turn 2, a modification request, correctly *ran* a refined command; but turn 3 — the **exact same wording as turn 1** — executed the command instead of answering, having been contaminated by the intervening command turn:

```
$ doit "how do i find python files modified this week?"
You can find Python files modified this week by using the `find` command...
find . -name "*.py" -mtime -7                          ← turn 1: answered (correct)
$ doit "modify it to also show file sizes"
$ find . -name "*.py" -mtime -7 -exec ls -lh {} \;     ← turn 2: ran (correct)
$ doit "how do i find python files modified this week?"
$ find . -name "*.py" -mtime -7 -exec ls -lh {} \;     ← turn 3: RAN, should have answered
```
*(logs/phase5/live_richer_interactions_history_bleed.txt)*

**Failed fix attempt.** The obvious move was to add a dedicated rule to `system_prompt.txt` stating that a literal question always gets `answer`:

> *"A request literally phrased as a question … always gets `answer`, even if a similar command was executed earlier in this conversation."*

This was added as its own **separate, later paragraph**. Re-testing live showed it did **not** work — turn 3 still executed:

```
$ doit "how do i find python files modified this week?"
$ find . -name '*.py' -mtime -7 -exec ls -lh {} \;     ← still ran, not answered
```
*(logs/phase5/live_richer_interactions_retest_after_prompt_fix.txt)*

**Root cause — the two contradicting rules.** During the failed attempt the prompt contained two rules in *different* places that pulled in opposite directions. The action-verb rule (earlier, and explicitly naming `find`) said run:

```
If the request describes a concrete action (create, write, edit, move, delete,
install, show, list, find, ...), always use run_command to actually do it — do
not describe the command instead of running it.
```

…while the newly-added exception sat as its **own separate paragraph elsewhere** in the prompt:

```
A request literally phrased as a question ("how do I find...", "what's the
command to list...") always gets answer, even if a similar command was executed
earlier in this conversation.
```

The two never met on the page. Faced with `"how do i find python files…"`, the model matched the concrete keyword `find` in the earlier, more specific action-verb rule and ran the command — a separate exception paragraph placed elsewhere couldn't override a specific keyword match sitting in an earlier rule. The model followed the closer, more specific instruction.

**The fix that worked.** Move the exception **inside** the action-verb rule itself, at the exact point of conflict, rather than in a standalone paragraph:

```
If the request describes a concrete action (create, write, edit, move, delete,
install, show, list, find, ...), always use run_command ... EXCEPTION: a request
literally phrased as a question ("how do I find...", "what's the command to
list...") is always answer, not run_command — the question wording overrides the
action verb, even if a similar command was executed earlier in this conversation.
```

Turn 3 then answered correctly:

```
$ doit "how do i find python files modified this week?"
You can find Python files modified this week by using the `find` command...
find . -name "*.py" -type f -mtime -7                  ← turn 3: answered, nothing executed
```
*(logs/phase5/live_richer_interactions_fixed.txt)*

**Lesson.** Prompt rules conflict by proximity and specificity, not merely by presence: a general exception must live *inside* the specific rule it is meant to override, not in a separate paragraph. (The same lesson recurred in Phase 6.5 — a warning only changed model behavior once it was moved into the tool-result text at the point of decision.)
