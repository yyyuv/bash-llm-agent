"""The tools the LPU can invoke, and their schemas.

The tool set IS the decision schema — the single contract every model
codes against (PLAN.md §1). The tools grow by phase:

    run_command   execute one shell command                       (Phase 1)
    answer        reply in plain text; also the signal that ends the loop
    ask_user      ask one clarifying question, resolved in-loop    (Phase 5)
    remember      save a durable fact about the user/environment   (Phase 6)
    forget        delete a stored fact by its id                   (Phase 6)
    change_dir    change the shell's cwd via the shell wrapper (D1)
    read_session  fetch another terminal's history in full         (Phase 8)

Schemas use the OpenAI function-calling format, which LiteLLM accepts
for every provider.
"""

import os
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
            "name": "ask_user",
            "description": (
                "Ask the user one short clarifying question and wait for "
                "their reply before continuing. Use this SPARINGLY — only "
                "when a wrong guess would touch different files with a "
                "destructive action, or when reasonable interpretations lead "
                "to materially different results and none is clearly the "
                "common one. Otherwise pick the most common interpretation, "
                "act, and state your assumption in the answer instead of "
                "asking."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": (
                            "The single question to ask. State the default "
                            "you will use if the user does not answer."
                        ),
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional list of concrete choices; shown to the "
                            "user as a numbered menu they can pick by number."
                        ),
                    },
                },
                "required": ["question"],
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
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": (
                "Save a durable fact or preference about the user or their "
                "environment so future doit runs can use it (e.g. 'my project "
                "folder is ~/school/llms/ass3', 'the user prefers ls sorted "
                "by size', 'always use eza instead of ls'). Use ONLY for "
                "stable facts worth keeping across sessions — never for "
                "transient details of the current request. This does not end "
                "the turn: you can also run a command or answer in the same "
                "turn."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {
                        "type": "string",
                        "description": (
                            "The fact to store, phrased so it still makes "
                            "sense on its own in a later, unrelated turn."
                        ),
                    },
                },
                "required": ["fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget",
            "description": (
                "Delete one stored memory by its id (the [id] shown in the "
                "known-facts block). Use this to remove a fact, or — together "
                "with remember — to change a fact the user has revised: "
                "forget the old id, then remember the new version."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "The id of the memory to delete, e.g. 'm3'.",
                    },
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "change_dir",
            "description": (
                "Change the current directory for the user's shell (e.g. "
                "'go to my project folder', 'cd into logs'). A subprocess "
                "cannot change its parent shell's directory directly — this "
                "just records the target; the shell wrapper performs the "
                "real cd after doit exits. Does not end the turn, but do NOT "
                "automatically add a follow-up command (e.g. ls) just to "
                "show the new directory's contents — only do that if the "
                "user's request explicitly asked to see/list what's there. "
                "If the request was only to change directory, answer to "
                "confirm and stop."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "The directory to change into — absolute, "
                            "relative to the current directory, or using ~."
                        ),
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_session",
            "description": (
                "Fetch the full recent history of ANOTHER terminal session "
                "by its id (the [id] shown in the 'Other recent terminal "
                "sessions' block). Use this ONLY when the user explicitly "
                "refers to work done in a different window and the one-line "
                "summary is not detailed enough to reproduce or discuss it "
                "(e.g. 'redo the exact folder task from the other terminal'). "
                "Do NOT use it for references to this session's own recent "
                "activity. This does not end the turn: the fetched history "
                "comes back to you and you continue in the same turn."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": (
                            "The id of the other session to read, e.g. "
                            "'f4a2', taken from the other-sessions block."
                        ),
                    },
                },
                "required": ["session_id"],
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


@dataclass
class ChangeDirResult:
    """Outcome of validating a change_dir request."""

    resolved_path: str
    error: str = ""


def resolve_change_dir(path: str) -> ChangeDirResult:
    """Expand and validate a change_dir target against the real filesystem.

    Resolves ~ and relative paths against the current process's cwd (which
    doit inherits from the shell that launched it), then checks the result
    is an existing directory. Validating here — rather than letting the
    shell wrapper's `cd` fail silently later — lets the controller feed a
    clear error back to the model instead of writing a bad cd_target file.
    """
    expanded = os.path.expanduser(path)
    resolved = os.path.abspath(expanded)
    if not os.path.isdir(resolved):
        return ChangeDirResult(resolved_path=resolved, error=f"no such directory: {resolved}")
    return ChangeDirResult(resolved_path=resolved)


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
