"""Persistent state under ~/.doit/, keyed by a per-terminal session id.

Layout:
    sessions/<session_id>.jsonl  one JSON record per completed turn
    memories.json                cross-session facts about the user (Phase 6)
    shell_hist/<session_id>      ts|cwd|cmd lines from the PROMPT_COMMAND/
                                  precmd shell hook (Phase 7 — every command
                                  this terminal ran, including doit itself)
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
SHELL_HIST_DIR = DOIT_HOME / "shell_hist"


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


def _read_all_turns(path: Path) -> list:
    """Read every turn record from a session JSONL file, oldest first.

    A missing file yields []. Malformed lines are skipped rather than
    crashing a live request.
    """
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
    return turns


def load_recent_turns(session_id: str, limit: int) -> list:
    """Return this session's most recent completed turns, oldest first.

    Reads the session's JSONL history and keeps the last `limit` records
    (Phase 4: K≈10). A missing file (first turn ever) yields []. Malformed
    lines are skipped rather than crashing a live request.
    """
    return _read_all_turns(SESSIONS_DIR / f"{session_id}.jsonl")[-limit:]


# --------------------------------------------------------------------------
# Cross-session awareness (Phase 8, Decision 10c) — summaries of OTHER
# terminals + on-demand fetch of one in full
# --------------------------------------------------------------------------

# Sessions untouched for longer than this are treated as stale and left out
# of the always-injected summaries block, so old terminals don't pollute
# context (the (a)-option con Decision 10 calls out). A user can still fetch
# one explicitly by id via read_session if they refer to it.
OTHER_SESSION_MAX_AGE_SECONDS = 24 * 3600


def _turn_ts(turn: dict):
    """Best-effort float timestamp of a turn record, or None if absent."""
    ts = turn.get("ts")
    try:
        return float(ts)
    except (TypeError, ValueError):
        return None


def list_other_sessions(
    current_session_id: str,
    max_sessions: int = 5,
    requests_per_session: int = 2,
    max_age_seconds: float = OTHER_SESSION_MAX_AGE_SECONDS,
) -> list:
    """Summarize OTHER terminals' sessions for cross-session awareness.

    Scans sessions/*.jsonl (excluding the current session), and for each
    one that has activity within max_age_seconds returns a lightweight
    record: {id, ts, cwd, requests} where `requests` is the last few
    plain-English requests made in that session — a cheap heuristic summary
    ("request + recent activity"), not an extra LLM summarize() call (that
    is the documented upgrade path if quality demands, Decision 10 note).

    Most-recently-active first, capped at max_sessions. This is what powers
    the always-injected summaries block; read_session fetches the full
    detail of one on demand.
    """
    if not SESSIONS_DIR.exists():
        return []
    now = time.time()
    summaries = []
    for path in SESSIONS_DIR.glob("*.jsonl"):
        sid = path.stem
        if sid == current_session_id:
            continue
        turns = _read_all_turns(path)
        if not turns:
            continue
        last_ts = _turn_ts(turns[-1])
        if max_age_seconds is not None and last_ts is not None and now - last_ts > max_age_seconds:
            continue
        requests = [t.get("request", "") for t in turns[-requests_per_session:] if t.get("request")]
        summaries.append(
            {"id": sid, "ts": last_ts, "cwd": turns[-1].get("cwd", ""), "requests": requests}
        )
    summaries.sort(key=lambda s: s["ts"] or 0, reverse=True)
    return summaries[:max_sessions]


# --------------------------------------------------------------------------
# User shell history (Phase 7) — what the user typed manually, per session
# --------------------------------------------------------------------------


def load_recent_user_commands(session_id: str, limit: int) -> list:
    """Return up to `limit` most recent commands the USER ran manually.

    Reads ~/.doit/shell_hist/<session_id>, written by the shell hook
    (PROMPT_COMMAND on bash, precmd on zsh) as `ts|cwd|cmd` lines for
    EVERY command the terminal runs, doit invocations included. This
    filters those back out: a command that is `doit` or starts with
    `doit ` is doit being invoked, not something doit itself ran — the
    simpler of the two signals from PLAN_DETAILED.md Section 9 (the other
    being cross-referencing sessions/*.jsonl), chosen because it needs no
    matching logic and is near-sufficient in practice.

    A missing file (no shell hook installed yet, or a brand-new terminal)
    yields [] rather than crashing a live request — same posture as
    load_recent_turns. Malformed lines are skipped.
    """
    path = SHELL_HIST_DIR / session_id
    if not path.exists():
        return []
    commands = []
    with open(path) as file:
        for line in file:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            ts, cwd, cmd = parts
            if cmd == "doit" or cmd.startswith("doit "):
                continue
            commands.append({"ts": ts, "cwd": cwd, "cmd": cmd})
    return commands[-limit:]


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


# --------------------------------------------------------------------------
# change_dir (D1 cd-trap fix) — a note file the shell wrapper reads on exit
# --------------------------------------------------------------------------


def cd_target_path(session_id: str) -> Path:
    """Path to this session's pending cd target, e.g. ~/.doit/cd_target_abc123."""
    return DOIT_HOME / f"cd_target_{session_id}"


def write_cd_target(session_id: str, resolved_path: str) -> None:
    """Record the directory the shell wrapper should cd into after doit exits.

    A Python subprocess cannot change its parent shell's cwd (D1) — this
    file is the handoff: the doit() shell function (shell/*_snippet.sh)
    reads it after `command doit` returns and performs the real cd, then
    deletes the file.
    """
    path = cd_target_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(resolved_path)
