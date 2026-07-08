# >>> doit integration >>>
# Per-terminal session id, stable across re-sourcing (":-" only sets it once).
export DOIT_SESSION="${DOIT_SESSION:-$(uuidgen | cut -c1-8)}"

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
