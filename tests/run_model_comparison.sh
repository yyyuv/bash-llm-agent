#!/usr/bin/env bash
# Phase-3 model-comparison harness.
#
#   tests/run_model_comparison.sh <MODEL> <ADAPTER> <LABEL>
#
# Writes ~/doit.cfg for (MODEL, ADAPTER), then runs the fixed Phase-3
# cases 1-8 PLUS the harder discriminator cases 56-60 (tests/cases.md) in a
# throwaway sandbox dir so the destructive cases don't touch anything real.
# The full terminal transcript is tee'd to logs/phase3/<LABEL>.txt; doit also
# auto-logs raw LLM request/response pairs to ~/.doit/logs/cmp_<LABEL>.jsonl
# (the report gold).
#
# Cases 1-8 are easy single-liners every model gets right (syntax drift only);
# cases 56-60 are deliberately hard SINGLE commands (multi-stage pipelines,
# BSD/GNU flag nuances, a portable rename loop) that expose where the ~4B
# locals fall apart while gpt-4o-mini holds up — the model-comparison content.
# We force `enable_plans = false` below so EVERY model is in pure
# single-command mode: the comparison is then a clean translation-quality
# test (one command, right or wrong), not a multi-step orchestration test.
#
# Examples:
#   set -a; source .env; set +a                              # only needed for the openai model
#   tests/run_model_comparison.sh openai/gpt-4o-mini    native   gpt4omini
#   tests/run_model_comparison.sh ollama/qwen3:4b-instruct native qwen3
#   tests/run_model_comparison.sh ollama/gemma3:4b      prompted gemma3
#
# Interactive confirms (cases 6/7/8 and 60) are scripted via stdin: 'y' runs,
# empty line aborts — matching the expected behavior in tests/cases.md.

set -u

if [ "$#" -ne 3 ]; then
  echo "usage: $0 <MODEL> <ADAPTER> <LABEL>" >&2
  exit 2
fi

MODEL="$1"; ADAPTER="$2"; LABEL="$3"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$REPO/logs/phase3"
OUT="$OUT_DIR/${LABEL}.txt"
mkdir -p "$OUT_DIR"

# 1) point doit at this model/adapter
cat > "$HOME/doit.cfg" <<EOF
[doit]
model = $MODEL
adapter = $ADAPTER
temperature = 0.0
max_steps = 1
command_timeout_seconds = 60
enable_plans = false
EOF

# 2) isolate this run's raw logs under a dedicated session id
export DOIT_SESSION="cmp_${LABEL}"
rm -f "$HOME/.doit/logs/${DOIT_SESSION}.jsonl" "$HOME/.doit/sessions/${DOIT_SESSION}.jsonl"

# 3) run everything inside a disposable sandbox so cases 6-8 are harmless
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
cd "$SANDBOX"

runq() {  # non-interactive case:  <label> <request>
  printf '\n===== CASE %s =====\n' "$1"
  printf '$ doit "%s"\n' "$2"
  doit "$2"
  printf '\n'
}

rund() {  # confirm-gated case:  <label> <request> <answer-piped-to-prompt>
  printf '\n===== CASE %s   (scripted answer: %q) =====\n' "$1" "$3"
  printf '$ doit "%s"\n' "$2"
  printf '%s\n' "$3" | doit "$2"
  printf '\n'
}

{
  printf '################ MODEL COMPARISON — %s ################\n' "$LABEL"
  printf 'model=%s  adapter=%s  session=%s  when=%s\n' \
         "$MODEL" "$ADAPTER" "$DOIT_SESSION" "$(date '+%Y-%m-%d %H:%M:%S')"
  printf 'sandbox=%s\n' "$SANDBOX"

  runq "1 hidden-files"   "show me all files here, including hidden ones"
  runq "2 disk-space"     "how much disk space is left?"
  runq "3 impossible"     "make my laptop fly"
  runq "4 joke"           "tell me a joke"
  runq "5 how-do-I"       "how do I see hidden files?"

  : > junk.txt
  rund "6 delete-confirm-y" "delete junk.txt" "y"
  [ -e junk.txt ] && echo "[check] junk.txt STILL EXISTS (unexpected for case 6)" \
                  || echo "[check] junk.txt deleted (expected for case 6)"

  : > junk.txt
  rund "7 delete-confirm-n" "delete junk.txt" ""
  [ -e junk.txt ] && echo "[check] junk.txt preserved (expected for case 7)" \
                  || echo "[check] junk.txt GONE (unexpected for case 7)"

  rund "8 redirect"       "list files sorted by size and save output into listing.txt" "y"

  # ---------------------------------------------------------------------
  # HARD DISCRIMINATOR CASES (56-60) — seed a richer sandbox first so the
  # commands have real data and a wrong command produces a visibly wrong
  # answer. Sizes/word-counts are chosen so the correct output is unambiguous.
  # ---------------------------------------------------------------------
  mkdir -p src sub
  # word-frequency fixture: "the"=4, "fox"=2, "apple"=3, "banana"=2, ...
  printf 'the quick brown fox the lazy dog the fox the end\n' >  notes.txt
  printf 'apple banana apple cherry apple banana\n'           >> notes.txt
  # size fixture: big.bin(120K) > sub/mid.bin(40K) > small.bin(5K)
  head -c 122880 /dev/zero > big.bin
  head -c  40960 /dev/zero > sub/mid.bin
  head -c   5120 /dev/zero > small.bin
  # non-blank-line fixture: one.py has 4 non-blank code lines, two.py has 2
  printf 'def a():\n\n    return 1\n\n\nprint(a())\n'          >  src/one.py
  printf 'x = 1\n\ny = 2\n'                                   >  src/two.py

  runq "56 largest-files" \
       "show me the 5 largest files under this directory tree, human-readable, biggest first"
  # correct: du -ah . | sort -rh | head -5   (big.bin should top the real files)

  runq "57 word-freq" \
       "what are the 3 most common words in notes.txt?"
  # correct: tr -s ' ' '\n' < notes.txt | sort | uniq -c | sort -rn | head -3  -> the(4), apple(3), ...

  runq "58 count-nonblank" \
       "count the total number of non-blank lines across all .py files here"
  # correct: e.g. grep -rvc '^$' --include='*.py' . | awk -F: '{s+=$2} END{print s}'  -> 5
  #          (one.py has 3 non-blank lines, two.py has 2)

  runq "59 recent-files" \
       "list only the files modified in the last 24 hours, newest first"
  # correct: find . -type f -mtime -1 ... (BSD/GNU nuance; ls -lt alone does NOT filter)

  # case 60 runs in its OWN clean subdir seeded with exactly 4 .txt files, so
  # the mechanical check has an unambiguous expectation. (The sandbox root has
  # stray .txt files by now — junk.txt from case 7's abort, listing.txt from
  # case 8's redirect — which would make "this folder" ambiguous here.)
  mkdir -p rename_case && cd rename_case
  : > report.txt ; : > todo.txt ; : > readme.txt ; : > log.txt   # exactly 4
  # feed several 'y' lines: some models add an ask_user confirmation step
  # BEFORE the destructive gate, so one 'y' isn't enough (the first is eaten by
  # the clarification, leaving EOF -> abort at the real gate). Extra y's on
  # stdin after doit exits are harmless.
  rund "60 rename-ext" \
       "rename every .txt file in this folder to have a .md extension instead" $'y\ny\ny'
  # correct: for f in *.txt; do mv -- "$f" "${f%.txt}.md"; done   (destructive -> y/N gate)
  remaining_txt=$(ls *.txt 2>/dev/null | wc -l | tr -d ' ')
  made_md=$(ls *.md 2>/dev/null | wc -l | tr -d ' ')
  echo "[check] case 60: *.txt remaining=$remaining_txt (expect 0), *.md now=$made_md (expect 4)"
  cd ..

  printf '\n################ END %s ################\n' "$LABEL"
} 2>&1 | tee "$OUT"

echo
echo "transcript : $OUT"
echo "raw LLM log: $HOME/.doit/logs/${DOIT_SESSION}.jsonl"
