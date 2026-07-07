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

# Command output longer than this is truncated before entering the LLM
# context; the full output is always kept on disk in the session record.
MAX_OUTPUT_CHARS_IN_CONTEXT = 4000

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


def truncate_for_context(text: str) -> str:
    """Shorten long command output before it enters the LLM context.

    Keeps the head and tail (both often matter — headers and totals) and
    says how much was cut. The full text stays on disk in the session log.
    """
    if len(text) <= MAX_OUTPUT_CHARS_IN_CONTEXT:
        return text
    head = text[: MAX_OUTPUT_CHARS_IN_CONTEXT - 1000]
    tail = text[-800:]
    cut = len(text) - len(head) - len(tail)
    return f"{head}\n... [{cut} characters truncated] ...\n{tail}"
