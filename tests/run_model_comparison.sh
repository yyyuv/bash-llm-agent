#!/usr/bin/env bash
# Phase-3 model-comparison harness.
#
#   tests/run_model_comparison.sh <MODEL> <ADAPTER> <LABEL>
#
# Writes ~/doit.cfg for (MODEL, ADAPTER), then runs the fixed Phase-3
# cases 1-8 (tests/cases.md) in a throwaway sandbox dir so the destructive
# cases don't touch anything real. The full terminal transcript is tee'd to
# logs/phase3/<LABEL>.txt; doit also auto-logs raw LLM request/response
# pairs to ~/.doit/logs/cmp_<LABEL>.jsonl (the report gold).
#
# Examples:
#   set -a; source .env; set +a                              # only needed for the openai model
#   tests/run_model_comparison.sh openai/gpt-4o-mini    native   gpt4omini
#   tests/run_model_comparison.sh ollama/qwen3:4b-instruct native qwen3
#   tests/run_model_comparison.sh ollama/gemma3:4b      prompted gemma3
#
# Interactive confirms (cases 6/7/8) are scripted via stdin: 'y' runs,
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

  printf '\n################ END %s ################\n' "$LABEL"
} 2>&1 | tee "$OUT"

echo
echo "transcript : $OUT"
echo "raw LLM log: $HOME/.doit/logs/${DOIT_SESSION}.jsonl"
