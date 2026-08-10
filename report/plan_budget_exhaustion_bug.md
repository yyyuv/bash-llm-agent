## Plan budget exhaustion: a plan that finished only 2 of 3 steps, silently (Phase 9, case 55)

Ready-to-insert source for the **Further extensions** section (a "what worked and
what didn't" case). Real data, `openai/gpt-4o-mini` native adapter, neutral
sandbox (`a.log`, `b.log`, `c.log`, `d.log`, random bytes).

An independent re-run of the multi-step plan pattern surfaced a real bug: the
turn ended having gzipped only **2 of the 3** target files, with no error and no
final answer. Request: *"find the 3 largest .log files here and gzip them"*.

```
Plan:
  1. find the 3 largest .log files in the current directory
  2. gzip each of the found .log files
$ find . -name '*.log' -exec du -b {} + | sort -n -r | head -n 3
du: invalid option -- b            <- du FAILED (GNU-only -b flag on BSD/macOS), but the
                                      pipeline's exit code is head's (0), so the failure
                                      was invisible to the rc!=0 retry check
$ find . -name '*.log' -exec du -k {} + | sort -n -r | head -n 3   <- model self-corrected
880  ./d.log
492  ./b.log
100  ./a.log
$ gzip ./d.log                     <- one command per file...
$ gzip ./b.log                     <- ...second file...
(turn ends -- budget exhausted, a.log NEVER gzipped, no final answer)
```
*(logs/phase9/live_budget_exhaustion_found_pre_fix.txt)*

**Root cause (two compounding factors).**
1. A shell pipeline (`cmd1 | cmd2`) reports only `cmd2`'s exit code, so `du`'s real
   failure (illegal `-b` flag) was hidden behind `head`'s success. The model fixed
   it on its own judgement — but "spent" a budget slot doing so, and because no
   non-zero exit code was ever seen, the self-correcting retry never knew to grant
   a compensating slot.
2. The model ran "gzip each" as **one command per file** instead of one batched
   `gzip` over all three, tripling the real cost against the plan's step-count
   budget (`len(steps) + PLAN_SLACK`, with `PLAN_SLACK = 2` at the time). Budget 4
   was reached after `gzip ./d.log` and `gzip ./b.log`; `a.log` was never gzipped.

**The fix (DECISIONS.md P9e).** Two changes: raise `PLAN_SLACK` 2 → 3
(`controller.py`), and add a system-prompt rule to batch same-type multi-target
actions into a single command. Re-verified live 3× afterward:

```
Plan:
  1. find the 3 largest .log files ...
  2. gzip each of the found files
$ find . -maxdepth 1 -name '*.log' -exec du -h {} + | sort -hr | head -n 3
880K ./d.log   492K ./b.log   100K ./a.log
$ gzip ./d.log ./b.log ./a.log     <- now batched into ONE command
The 3 largest .log files have been successfully gzipped.
-- files after: a.log.gz b.log.gz c.log d.log.gz  (all 3 real targets done, c.log untouched)
```
*(logs/phase9/live_plan_batched_gpt4omini.txt)*

**Lesson.** A step-count budget is only safe if each step is one command. A model
that fans a step out into N commands, or silently burns a slot recovering from a
pipeline-masked failure, can exhaust the budget mid-task. The robust fixes are
structural (more slack) and behavioural (batch same-type actions) — not a smarter
exit-code check, because a pipeline's exit code simply cannot see a failure in an
upstream stage.
