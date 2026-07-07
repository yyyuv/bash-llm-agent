"""Standalone check of doitlib.safety.check_command() against a fixed
case list, written to verify the Phase 2 regex guard before wiring it
into the controller. Not part of the doit package; run manually:

    python3 logs/phase2/safety_guard_tests.py

Writes results to logs/phase2/safety_guard_results.json.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from doitlib import safety

CASES = [
    # (command, model_says_destructive, note)
    ("ls -la", False, "plain read-only"),
    ("rm file.txt", False, "model under-flagged an obvious delete; guard must override"),
    ("ls > files.txt", False, "sneaky redirect turns a read command into a write"),
    ('cat a.txt | tee b.txt', False, "tee writes despite looking like a read pipeline"),
    ('find . -name "*.tmp" -delete', False, "find -delete"),
    ("sudo rm -rf /", True, "sudo must be flagged regardless of model"),
    ("vim file.txt", False, "always-interactive editor"),
    ("less file.txt", False, "always-interactive pager"),
    ("ssh myhost", False, "bare ssh drops into a remote shell -> interactive"),
    ("ssh myhost ls", False, "ssh with a command is non-interactive -> should NOT be flagged"),
    ("python3 script.py", False, "python with a script arg is non-interactive"),
    ("python3", False, "bare python drops into a REPL -> interactive"),
    ("git commit -m x", False, "git commit is destructive"),
    ("git log", False, "git log is read-only"),
    ('grep "rm -rf" notes.txt', False, "known false-positive risk: 'rm -rf' appears inside a string literal"),
]


def main() -> None:
    results = []
    for command, model_says_destructive, note in CASES:
        check = safety.check_command(command, model_says_destructive)
        results.append(
            {
                "command": command,
                "model_says_destructive": model_says_destructive,
                "note": note,
                "guard_result": {
                    "is_destructive": check.is_destructive,
                    "guard_overrode_model": check.guard_overrode_model,
                    "is_sudo": check.is_sudo,
                    "is_interactive": check.is_interactive,
                },
            }
        )
        print(
            f"{command!r:45} destructive={check.is_destructive!s:5} "
            f"override={check.guard_overrode_model!s:5} sudo={check.is_sudo!s:5} "
            f"interactive={check.is_interactive}"
        )

    out_path = Path(__file__).resolve().parent / "safety_guard_results.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
