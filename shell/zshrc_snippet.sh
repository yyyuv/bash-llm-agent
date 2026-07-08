# >>> doit integration >>>
# Per-terminal session id, stable across re-sourcing (":-" only sets it once).
export DOIT_SESSION="${DOIT_SESSION:-$(uuidgen | cut -c1-8)}"
mkdir -p ~/.doit/shell_hist

# User shell-history hook (Phase 7, user awareness): log every command this
# terminal runs — INCLUDING doit invocations themselves — as ts|cwd|cmd to
# ~/.doit/shell_hist/$DOIT_SESSION. doit distinguishes "commands the user
# ran manually" from its own commands in Python (anything starting with
# "doit " is an invocation, not something doit ran — PLAN_DETAILED.md
# Section 9), so this hook stays dumb and shell-agnostic; identical format
# to the bash variant. Guarded against re-logging the same command on
# every empty-Enter prompt redraw. add-zsh-hook composes with any other
# precmd hooks already defined elsewhere in the user's zshrc.
_doit_log_history() {
  local cmd
  cmd=$(fc -ln -1)
  if [ -n "$cmd" ] && [ "$cmd" != "$_DOIT_LAST_LOGGED" ]; then
    echo "$(date +%s)|$(pwd)|$cmd" >> ~/.doit/shell_hist/$DOIT_SESSION
    _DOIT_LAST_LOGGED="$cmd"
  fi
}
autoload -Uz add-zsh-hook
add-zsh-hook precmd _doit_log_history

# Wrapper so change_dir can affect THIS shell: doit itself is a subprocess
# and cannot change its parent shell's cwd (D1, DECISIONS.md). change_dir
# writes the target to ~/.doit/cd_target_$DOIT_SESSION; this function reads
# it after doit exits and performs the real cd.
doit() {
  command doit "$@"
  local t=~/.doit/cd_target_$DOIT_SESSION
  if [ -f "$t" ]; then
    cd "$(cat "$t")" && rm -f "$t"
  fi
}
# <<< doit integration <<<
