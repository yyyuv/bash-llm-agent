"""Persistent state under ~/.doit/, keyed by a per-terminal session id.

Layout:
    sessions/<session_id>.jsonl  one JSON record per completed turn
    memories.json                cross-session facts about the user (Phase 6)
    logs/<session_id>.jsonl      raw LLM requests/responses (report evidence)

The session id comes from the DOIT_SESSION environment variable, which
the shell integration snippet sets per terminal. Without the snippet we
fall back to "default" so doit still works.

Memories are deliberately NOT keyed by session: a fact the user states in
one terminal ("this is my project folder") must be visible everywhere, so
memories.json is a single shared list (Phase 6 / PLAN §State layout).
"""

import json
import os
import time
from pathlib import Path

DOIT_HOME = Path.home() / ".doit"
SESSIONS_DIR = DOIT_HOME / "sessions"
LOGS_DIR = DOIT_HOME / "logs"
MEMORIES_PATH = DOIT_HOME / "memories.json"


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


# --------------------------------------------------------------------------
# Memory (Phase 6) — a single shared list of {id, ts, text}, not per-session
# --------------------------------------------------------------------------


def load_memories() -> list:
    """Return every stored memory, oldest first: [{id, ts, text}].

    A missing or malformed file yields [] rather than crashing a live
    request — the same defensive posture as load_recent_turns.
    """
    if not MEMORIES_PATH.exists():
        return []
    try:
        data = json.loads(MEMORIES_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def add_memory(text: str) -> dict:
    """Store one new fact and return its record {id, ts, text}.

    The id is the visible handle the model uses to forget/replace this fact
    later (e.g. "m3" in the known-facts block), so it must be stable — we
    never rewrite existing ids when appending.
    """
    memories = load_memories()
    record = {"id": _next_memory_id(memories), "ts": time.time(), "text": text}
    memories.append(record)
    _write_memories(memories)
    return record


def forget_memory(memory_id: str) -> bool:
    """Delete the memory with this id. Returns True if one was removed.

    Editing a fact ("I changed my mind about the sort order") is forget +
    add_memory: the model reads the id from context, forgets it, and stores
    the revised version.
    """
    memories = load_memories()
    kept = [m for m in memories if str(m.get("id")) != str(memory_id)]
    if len(kept) == len(memories):
        return False
    _write_memories(kept)
    return True


def _next_memory_id(memories: list) -> str:
    """Return the next 'm<n>' id: one past the highest numeric id in use.

    Based on the current maximum so ids stay short and readable. After the
    highest memory is forgotten an id can be reused, which is harmless at
    this scale (ids only need to be unique among the facts live at once, so
    the model can reference them in a single turn) — documented in
    DECISIONS.md P6a.
    """
    highest = 0
    for memory in memories:
        mid = str(memory.get("id", ""))
        if mid.startswith("m") and mid[1:].isdigit():
            highest = max(highest, int(mid[1:]))
    return f"m{highest + 1}"


def _write_memories(memories: list) -> None:
    """Persist the full memory list, creating ~/.doit/ if needed."""
    MEMORIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMORIES_PATH.write_text(json.dumps(memories, indent=2))


def log_llm_call(session_id: str, request: dict, response: dict) -> None:
    """Save one raw LLM request/response pair (full, untruncated)."""
    _append_jsonl(
        LOGS_DIR / f"{session_id}.jsonl",
        {"ts": time.time(), "request": request, "response": response},
    )
