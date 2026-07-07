"""The deterministic safety guard (defense-in-depth layer 2).

Layer 1 is the model's own `is_destructive` self-report (tools.py). This
module never trusts that alone: it scans the literal command text for
write/destructive patterns and overrides the model whenever it claimed
"safe" but the text says otherwise. Never let a model alone near `rm -rf`.

Also flags interactive/full-screen programs (which would hang our
subprocess capture) and `sudo` (never run, no override possible).
"""

import re
from dataclasses import dataclass

# Each pattern matches a command-line construct that writes, deletes, or
# otherwise mutates state. Word-boundary tokens for command names so we
# don't match substrings inside unrelated words (e.g. "format" containing
# no "rm", but "confirm" would false-positive on a bare "rm" without \b).
_DESTRUCTIVE_PATTERNS = [
    r"\brm\b", r"\bmv\b", r"\bcp\b", r"\bmkdir\b", r"\btouch\b",
    r"\bchmod\b", r"\bchown\b", r"\bdd\b", r"\bln\b", r"\btee\b",
    r"\bsed\b.*-i\b", r"\btruncate\b", r"\bxargs\b.*\brm\b",
    r">>?(?!&)",  # redirection (> or >>), but not the >& / &> fd-merge forms
    r"\bgit\s+(commit|push|reset|clean)\b",
    r"\bfind\b.*-delete\b",
    r"\bcurl\b.*\|\s*(sh|bash)\b",
    r"\bwget\b.*\|\s*(sh|bash)\b",
]
_DESTRUCTIVE_RE = re.compile("|".join(_DESTRUCTIVE_PATTERNS))

_SUDO_RE = re.compile(r"\bsudo\b")

# Full-screen / editor programs: always interactive, regardless of args
# (our subprocess capture would just hang forever on these).
_ALWAYS_INTERACTIVE_PROGRAMS = {
    "vim", "vi", "nano", "emacs", "top", "htop", "less", "more", "man",
}

# Programs that are only interactive when invoked with no further
# arguments (they drop into a REPL); with args they run a script or a
# single command non-interactively and are perfectly safe to run.
_INTERACTIVE_WHEN_BARE_PROGRAMS = {"python", "python3", "mysql", "psql"}

# ssh is bare-interactive up to and including a hostname (ssh, ssh host);
# it only becomes non-interactive once a remote command follows the
# host. Handled separately from the set above because "bare" for ssh
# means "no command", not "no arguments at all". Known limitation: a
# flag that takes a separate value (e.g. "ssh -p 2222 host") is
# misread as a two-word command and wrongly treated as non-interactive
# — acceptable for this assignment's scope, documented rather than
# fixed with a full ssh flag table.


@dataclass
class SafetyCheck:
    """The guard's verdict on one command."""

    is_destructive: bool
    guard_overrode_model: bool  # true when the model said safe but the guard disagreed
    is_sudo: bool
    is_interactive: bool


def check_command(command: str, model_says_destructive: bool) -> SafetyCheck:
    """Evaluate one command against the deterministic guard.

    is_destructive in the result is the guard's own determination: the
    model's flag is treated as a lower bound (a model can never
    downgrade a command the guard flags as destructive).
    """
    guard_flags_destructive = bool(_DESTRUCTIVE_RE.search(command))
    is_destructive = model_says_destructive or guard_flags_destructive
    return SafetyCheck(
        is_destructive=is_destructive,
        guard_overrode_model=guard_flags_destructive and not model_says_destructive,
        is_sudo=bool(_SUDO_RE.search(command)),
        is_interactive=_is_interactive_command(command),
    )


def _is_interactive_command(command: str) -> bool:
    """True if running this command would open a full-screen/REPL program.

    Checks only the first token (so a pipeline like `git log | less` is
    not caught — `less` there is reading piped input, not a bare
    full-screen invocation... though `git log` piping into `less` still
    opens `less` interactively; this simple first-token check is a
    deliberately conservative approximation, not a shell parser).
    """
    tokens = command.strip().split()
    if not tokens:
        return False
    program_name = tokens[0].rsplit("/", 1)[-1]  # strip a leading path
    if program_name in _ALWAYS_INTERACTIVE_PROGRAMS:
        return True
    if program_name in _INTERACTIVE_WHEN_BARE_PROGRAMS and len(tokens) == 1:
        return True
    if program_name == "ssh":
        non_flag_args = [t for t in tokens[1:] if not t.startswith("-")]
        return len(non_flag_args) <= 1  # nothing, or just a hostname -> no remote command
    return False
