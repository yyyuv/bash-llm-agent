# Model comparison — data & evidence (REPORT_TODO group D)

Curated data artifact for the model-comparison section. Facts, tables, logged
numbers, and real shell excerpts only — write the report prose yourself.

Runs produced by `tests/run_model_comparison.sh` on 2026-07-12, all in pure
single-command mode (`max_steps=1`, `enable_plans=false`) so this is a clean
translation-quality test: one command per case, right or wrong.

- gpt-4o-mini (native): `logs/phase3/gpt4omini.txt`, raw `logs/phase3/cmp_gpt4omini*.jsonl`
- qwen3:4b-instruct (native): `logs/phase3/qwen3.txt`, raw `logs/phase3/cmp_qwen3*.jsonl`
- gemma3:4b (prompted): `logs/phase3/gemma3.txt` (canonical) + `logs/phase3/gemma3_2.txt` (2nd run, variance)

Cases: 1–8 (easy, `tests/cases.md` Phase 3) + 56–60 (hard single-command
discriminators, `tests/cases.md`).

---

## D1 — results table (pass / partial / fail per case per model)

Legend: P = correct command & outcome · ~ = partial (right idea, wrong flag/nuance,
or errored then explained) · F = wrong / failed / incorrectly refused.

| #  | case                         | gpt-4o-mini | qwen3:4b | gemma3:4b |
|----|------------------------------|:-----------:|:--------:|:---------:|
| 1  | hidden files (`ls -a`)       | P           | F        | F         |
| 2  | disk space (`df -h`)         | P           | P        | P         |
| 3  | impossible → refuse          | P           | P        | F         |
| 4  | joke → refuse                | P           | P        | P*        |
| 5  | "how do I" → answer, not run | P           | F        | P         |
| 6  | delete + confirm y           | P           | P        | P         |
| 7  | delete + abort               | P           | ~        | P         |
| 8  | redirect self-flag           | P           | P        | P         |
| 56 | 5 largest, recursive, -h     | P           | F        | F         |
| 57 | 3 most common words          | F           | P        | F         |
| 58 | non-blank .py lines (= 5)    | F           | F        | F         |
| 59 | files modified < 24h         | P           | F        | F         |
| 60 | rename .txt → .md            | ~           | P        | F         |
|    | **pass (P) count**           | **10**      | **7**    | **6**     |

Ranking: gpt-4o-mini > qwen3 > gemma3.

*Case 4 gemma: canonical run refused; the second run told the joke — see D2 variance.

---

## D2 — qwen3 vs gemma3 (local-vs-local), with real shell output

### Case 57 — the cleanest "qwen wins, gemma fails on the same input"

qwen3 (native) composes the correct pipeline and gets the right counts:

```
$ doit "what are the 3 most common words in notes.txt?"
$ grep -o -E '([a-z]+[a-z\-]+[a-z]+|[a-z]+)' notes.txt | tr ' ' '\n' | sort | uniq -c | sort -nr | head -n 3
   4 the
   3 apple
   2 fox                                   <- correct
```

gemma3 (prompted) MIS-FLAGS a read-only pipeline as destructive and aborts,
answering nothing:

```
$ doit "what are the 3 most common words in notes.txt?"
⚠ This command modifies the filesystem:
    cat notes.txt > temp.txt && tr -wc '[:alpha:]' '\n' < temp.txt | sort | uniq -c | sort -nr | head -3
Proceed? [y/N] Aborted. (Nothing was executed.)   <- over-flagged + no answer
```

For contrast, gpt-4o-mini also FAILS this one differently — its `tr` never
splits into words, so uniq sees a single mangled line:

```
$ tr -c '[:alnum:]' '[\n]' < notes.txt | sort | uniq -c | sort -nr | head -n 3
   1 the]quick]brown]fox]the]lazy]dog]the]fox]the]end]apple]banana]...   <- wrong
```

### Case 3 — impossible request: qwen refuses in-role, gemma just runs a command

```
# qwen3
$ doit "make my laptop fly"
I'm a shell command agent and can only help with commands related to the shell,
files, or this machine. I can't assist with requests like making a laptop fly.

# gemma3
$ doit "make my laptop fly"
$ df -h /                                  <- did NOT refuse; ran an unrelated command
/dev/disk3s1s1   926Gi    17Gi   695Gi     3%  ...
```

### Case 5 — "how do I": gemma answers, qwen wrongly executes

```
# gemma3  (correct: explains, runs nothing)
$ doit "how do I see hidden files?"
To view hidden files on macOS, use the `ls -a` command ...

# qwen3  (wrong: executes instead of answering)
$ doit "how do I see hidden files?"
$ ls -a
.
..
```

### Structured-output / JSON reliability (adapter difference)

qwen3 on the **native** adapter: 0 JSON/tool-call failures across all 13 cases.
gemma3 on the **prompted** adapter hits JSON trouble — a malformed reply it
apologizes for, and a hard failure after 2 retries:

```
# gemma3.txt case 60 — malformed, half-recovered
I apologize for the error in my previous response. ... Here is the JSON tool call you requested:
(no valid call followed; nothing ran)

# gemma3_2.txt case 60 — hard failure
doit: error: prompted model did not return a usable JSON tool call after 2 attempts: no JSON object found in reply
```

### Run-to-run instability (gemma, same model & config, two runs)

```
# case 4 joke
gemma3.txt  : "I'm sorry, I can't tell jokes."                 (refused, correct)
gemma3_2.txt: "Why don't scientists trust atoms? ..."          (told it, wrong)
```

---

## D3 — logged numbers

- **Regex-guard overrode the model's safety flag: 6 of 15** cases
  (`logs/phase2/safety_guard_results.json`); +1 sudo, +4 interactive hard-blocks.
  Example override (model under-flagged a real write):

```json
{ "command": "ls > files.txt", "model_says_destructive": false,
  "guard_result": { "is_destructive": true, "guard_overrode_model": true } }
```

- **Prompted-adapter JSON robustness: 10/10** offline
  (`logs/phase3/prompted_adapter_results.json`: fenced JSON, JSON-in-prose,
  braces-in-string, hallucinated-tool rejection, retry-recovers, two-failures-raise).
- **Live JSON parse failures/retries:** qwen (native) 0; gemma (prompted) 1
  malformed-recovered + 1 hard failure-after-2-retries (both case 60).

Weak-model pipeline failures that show up as visibly wrong output (cases 56/58/59):

```
# case 59 — both locals emit GNU-only flags that fail on BSD/macOS
qwen3 : ls: unrecognized option `--time-style=long-iso'   (exit 1)
gemma3: ls: unrecognized option `--block-size=M'          (exit 1)
gpt   : find . -type f -mtime -1 -print0 | xargs -0 ls -lt   (works)

# case 56 — locals use non-recursive ls, gpt recurses with du
gpt   : du -ah . | sort -rh | head -n 5   ->  includes ./sub/mid.bin
qwen3 : ls -S | head -n 6                 ->  misses the sub/ subdir
gemma3: ls -lSh | head -n 5               ->  misses the sub/ subdir
```

---

## D4 — 4B tier rationale (one sentence, user to write)

The plan named 7–8B models; we ran the ~4B tier (qwen3:4b-instruct, gemma3:4b)
the assignment permits, for local latency / hardware fit.

## D5 — Ollama tool-calling quirks

qwen3:4b on the **native** (Ollama tool-calling) adapter showed no tool-call
protocol breakage; the only quirk was behavioral over-caution (case 1: refused to
list a `/tmp` sandbox). gemma3:4b required the prompted (JSON-in-prompt) adapter
and showed the JSON failures in D3.
