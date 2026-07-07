"""The tools the LPU can invoke, and their schemas.

The tool set IS the decision schema — the single contract every model
codes against (PLAN.md §1). Phase 1 ships two tools:

    run_command  execute one shell command
    answer       reply in plain text; also the signal that ends the loop

Schemas use the OpenAI function-calling format, which LiteLLM accepts
for every provider.
"""

import subprocess
from dataclasses import dataclass

# D7 tiered truncation budgets (Phase 4). Output entering the LLM context
# is trimmed to head+tail; the full text always stays on disk in the
# session record. Two budgets, not one: the "hot" budget is for the
# current turn's live output — it drives the next decision, so keep it
# rich; the "cold" budget is for older turns replayed into history, where
# only the gist matters and the K-turn multiplier makes bytes expensive.
# (DECISIONS.md D7 — chosen over a metadata-only cliff for older turns.)
HOT_HEAD_CHARS = 3000
HOT_TAIL_CHARS = 1000
COLD_HEAD_CHARS = 1000
COLD_TAIL_CHARS = 300

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Execute one shell command on the user's machine and "
                "show them the output."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The exact shell command to run.",
                    },
                    "is_destructive": {
                        "type": "boolean",
                        "description": (
                            "true if the command could modify or delete "
                            "anything (files, permissions, git state, "
                            "installed software); false only if it is "
                            "purely read-only."
                        ),
                    },
                    "explanation": {
                        "type": "string",
                        "description": "One short sentence: what the command does.",
                    },
                },
                "required": ["command", "is_destructive", "explanation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "answer",
            "description": (
                "Reply to the user in plain text without running anything. "
                "Also use this to finish: explain results, answer questions, "
                "say why a request is impossible, or politely decline "
                "off-topic requests."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The reply to show the user.",
                    },
                },
                "required": ["text"],
            },
        },
    },
]


@dataclass
class CommandResult:
    """What happened when a shell command ran."""

    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False


def run_command(command: str, shell_path: str, timeout_seconds: int) -> CommandResult:
    """Run one command through the user's shell, capturing all output."""
    try:
        completed = subprocess.run(
            command,
            shell=True,
            executable=shell_path,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return CommandResult(completed.stdout, completed.stderr, completed.returncode)
    except subprocess.TimeoutExpired:
        return CommandResult(
            stdout="",
            stderr=f"command timed out after {timeout_seconds}s",
            returncode=-1,
            timed_out=True,
        )


def truncate_for_context(
    text: str,
    head_chars: int = HOT_HEAD_CHARS,
    tail_chars: int = HOT_TAIL_CHARS,
) -> str:
    """Shorten long command output before it enters the LLM context.

    Keeps the head and tail and says how much was cut — head for listings
    (the useful part is at the top), tail for errors (they print at the
    end). Defaults to the hot budget (current turn); pass the cold budget
    (tools.COLD_*) when replaying older turns into history. The full text
    stays on disk in the session log.
    """
    if len(text) <= head_chars + tail_chars:
        return text
    head = text[:head_chars]
    tail = text[-tail_chars:]
    cut = len(text) - len(head) - len(tail)
    return f"{head}\n... [{cut} characters truncated] ...\n{tail}"
