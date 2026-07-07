"""Persistent state under ~/.doit/, keyed by a per-terminal session id.

Layout:
    sessions/<session_id>.jsonl  one JSON record per completed turn
    logs/<session_id>.jsonl      raw LLM requests/responses (report evidence)

The session id comes from the DOIT_SESSION environment variable, which
the shell integration snippet sets per terminal. Without the snippet we
fall back to "default" so doit still works.
"""

import json
import os
import time
from pathlib import Path

DOIT_HOME = Path.home() / ".doit"
SESSIONS_DIR = DOIT_HOME / "sessions"
LOGS_DIR = DOIT_HOME / "logs"


def get_session_id() -> str:
    """Return this terminal's session id (or "default" if unset)."""
    return os.environ.get("DOIT_SESSION", "default")


def _append_jsonl(path: Path, record: dict) -> None:
    """Append one record as a JSON line, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as file:
        file.write(json.dumps(record, default=str) + "\n")


def record_turn(session_id: str, turn_record: dict) -> None:
    """Save one completed turn to the session's history file.

    A turn record looks like:
    {ts, cwd, request, steps: [{tool, args, stdout, stderr, rc}], final_answer}
    """
    _append_jsonl(SESSIONS_DIR / f"{session_id}.jsonl", turn_record)


def load_recent_turns(session_id: str, limit: int) -> list:
    """Return this session's most recent completed turns, oldest first.

    Reads the session's JSONL history and keeps the last `limit` records
    (Phase 4: K≈10). A missing file (first turn ever) yields []. Malformed
    lines are skipped rather than crashing a live request.
    """
    path = SESSIONS_DIR / f"{session_id}.jsonl"
    if not path.exists():
        return []
    turns = []
    with open(path) as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                turns.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return turns[-limit:]


def log_llm_call(session_id: str, request: dict, response: dict) -> None:
    """Save one raw LLM request/response pair (full, untruncated)."""
    _append_jsonl(
        LOGS_DIR / f"{session_id}.jsonl",
        {"ts": time.time(), "request": request, "response": response},
    )
