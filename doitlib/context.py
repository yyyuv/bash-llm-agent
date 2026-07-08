"""Builds the message list sent to the LPU.

Each function here maps 1:1 to one element of the ACDL spec in acdl/
(agent_instructions <-> AGENT_INSTRUCTIONS, environment_block <-> the
env.* block, user_request <-> env.user_request). Keep that mapping
intact when editing — the graded ACDL documentation must match the real
context assembly.

Prompt text lives in prompts/ as files, so the report can quote the
templates verbatim.
"""

import datetime
import os
import platform
import time
from pathlib import Path

from . import state, tools
from .config import Config, resolve_shell

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# K: replay at most the last K prior turns of this session as context
# (PLAN.md Phase 4). Older turns are dropped for now; a Phase 9 extension
# would summarize them instead.
HISTORY_TURNS = 10

# Cap on how many manually-run shell commands (Phase 7) are shown per turn —
# same rationale as HISTORY_TURNS: bound the block instead of dumping an
# ever-growing per-terminal file into every request.
USER_SHELL_HISTORY_LIMIT = 20

# How many turns of ANOTHER session read_session renders in full (Phase 8).
# Detail-on-demand, so this can be more generous than a summary but still
# bounded — the model asked for one specific other terminal, not all of them.
READ_SESSION_TURNS = 10


def agent_instructions() -> str:
    """AGENT_INSTRUCTIONS: the static system prompt (role + policies)."""
    return (PROMPTS_DIR / "system_prompt.txt").read_text()


def environment_block(config: Config) -> str:
    """env.cwd / env.datetime / env.shell / env.os: where and when we are.

    Included so the LLM emits commands that fit this shell and OS.
    """
    template = (PROMPTS_DIR / "environment_block.txt").read_text()
    return template.format(
        cwd=os.getcwd(),
        datetime=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        shell=resolve_shell(config),
        os_name=f"{platform.system()} ({platform.machine()})",
    )


def user_request(request: str) -> str:
    """env.user_request: the plain-English request, verbatim."""
    return request


def memory_block() -> str:
    """sys.memories: every stored fact about the user, labeled with its id.

    Decision 9, option (a): ALL memories are injected on EVERY turn — no
    relevance filtering. At this scale (dozens of facts at most) the token
    cost is negligible and nothing relevant is ever silently missing;
    embedding-based top-k retrieval is described as future work / a possible
    Phase 9 extension (DECISIONS.md D9). The visible [id]s are what let the
    model forget or replace a specific fact when the user revises it.

    Returns "" when there are no memories, so build_messages can skip the
    block entirely rather than emit an empty labeled header.
    """
    memories = state.load_memories()
    if not memories:
        return ""
    lines = "\n".join(f"- [{m['id']}] {m['text']}" for m in memories)
    template = (PROMPTS_DIR / "memory_block.txt").read_text()
    return template.format(memories=lines)


def history_messages(session_id: str) -> list:
    """ForEach(@t in last K turns): prior turns replayed as chat messages.

    The single ACDL element that distinguishes v4 from v1–v3. Each past
    turn is spliced back in as real chat messages (the shape models were
    trained on), not a text dump — so a follow-up like "now sort them by
    date" reads naturally as referring to the previous turn's output. We
    do NOT classify follow-up vs. new command; with history in context
    the LLM resolves the reference itself.
    """
    messages = []
    for turn in state.load_recent_turns(session_id, HISTORY_TURNS):
        messages.extend(_replay_turn(turn))
    return messages


def _replay_turn(turn: dict) -> list:
    """Render one past turn (one @t) as replayed chat messages.

    U: the request -> for each executed command  A: the command run and
    U: its cold-truncated output -> A: the final answer (when the turn
    produced one). Uses plain user/assistant messages, never the native
    tool role: a cross-turn replay has no live tool_call_id to anchor a
    tool-role message to, and providers reject an orphan tool message.
    Older-turn output uses the D7 cold budget (tools.COLD_*).
    """
    messages = [{"role": "user", "content": turn.get("request", "")}]
    for step in turn.get("steps", []):
        if step.get("tool") == "ask_user":
            question = step.get("args", {}).get("question", "")
            messages.append({"role": "assistant", "content": f"(asked) {question}"})
            reply = step.get("reply")
            messages.append(
                {"role": "user", "content": f"(answered) {reply}" if reply else "(no answer)"}
            )
            continue
        if step.get("tool") != "run_command":
            continue
        command = step.get("args", {}).get("command", "")
        if step.get("rc") is None:
            # never executed (sudo / interactive / declined confirmation)
            reason = step.get("blocked_reason", "not run")
            messages.append(
                {"role": "assistant", "content": f"(did not run — {reason}): {command}"}
            )
            continue
        messages.append({"role": "assistant", "content": f"$ {command}"})
        stdout = tools.truncate_for_context(
            step.get("stdout", ""), tools.COLD_HEAD_CHARS, tools.COLD_TAIL_CHARS
        )
        body = f"exit {step.get('rc')}\n{stdout}"
        stderr = step.get("stderr", "")
        if stderr.strip():
            stderr = tools.truncate_for_context(
                stderr, tools.COLD_HEAD_CHARS, tools.COLD_TAIL_CHARS
            )
            body += f"\n[stderr] {stderr}"
        messages.append({"role": "user", "content": body})
    final = turn.get("final_answer")
    if final:
        messages.append({"role": "assistant", "content": final})
    return messages


def user_shell_history_block(session_id: str) -> str:
    """USER_SHELL_HISTORY: commands the user typed manually in this terminal.

    Phase 7 (Section 9 / user awareness): the shell hook logs every command
    this terminal runs, doit invocations included; state.load_recent_user_
    commands already filtered those back out, so everything here is
    something the USER ran directly — cd, mkdir, editing a file, running a
    script — that doit itself never saw or executed. This is what lets
    "summarize what I just did" or "why did my last command fail" resolve
    against manual activity, distinct from the replayed session history
    above (which is doit's own tool calls).

    Returns "" when there is no shell history yet (hook not installed, or
    nothing typed this terminal), so build_messages can skip the block.
    """
    commands = state.load_recent_user_commands(session_id, USER_SHELL_HISTORY_LIMIT)
    if not commands:
        return ""
    lines = "\n".join(f"  [in {c['cwd']}] {c['cmd']}" for c in commands)
    template = (PROMPTS_DIR / "user_shell_history_block.txt").read_text()
    return template.format(commands=lines)


def _humanize_age(ts, now: float) -> str:
    """Render a timestamp as a rough "N min/hours ago" for the summaries.

    Coarse on purpose — the summaries block just needs to convey recency
    ("which terminal did I touch most recently"), not a precise clock.
    """
    if ts is None:
        return "recently"
    seconds = max(0, int(now - ts))
    if seconds < 90:
        return "just now"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes} min ago"
    hours = minutes // 60
    return f"{hours} hr ago"


def other_sessions_block(session_id: str) -> str:
    """ForEach(s: sys.other_sessions): one-line summaries of OTHER terminals.

    Decision 10c (always-inject summaries + a read_session fetch tool).
    This is the always-on half: each other recently-active session is
    summarized in a single line (id, how long ago, cwd, its recent
    requests) so an explicit cross-reference like "redo the folder task
    from the other window" has something to latch onto. The visible [id]
    is what the model passes to read_session when the summary is too thin
    to actually redo the task.

    Deliberately does NOT drown the current turn in other sessions' detail:
    implicit references ("sort them") must stay local to this session's own
    replayed history, which is why these are one-liners, not full turns.
    Returns "" when there are no other recent sessions, so build_messages
    skips the block — the common single-terminal case adds nothing.
    """
    sessions = state.list_other_sessions(session_id)
    if not sessions:
        return ""
    now = time.time()
    lines = []
    for session in sessions:
        recent = "; ".join(session["requests"]) or "(no recorded request)"
        cwd = session["cwd"] or "unknown dir"
        lines.append(
            f"- session {session['id']} ({_humanize_age(session['ts'], now)}, in {cwd}): {recent}"
        )
    template = (PROMPTS_DIR / "other_sessions_block.txt").read_text()
    return template.format(sessions="\n".join(lines))


def render_session_detail(target_session_id: str, current_session_id: str) -> str:
    """Render another session's recent turns in full, for the read_session tool.

    The detail-on-demand half of Decision 10c: when a summary line is too
    thin to reproduce a task, the model calls read_session(id) and gets
    this — a compact transcript of that session's last READ_SESSION_TURNS
    turns (request, the commands it ran, and its final answer). Returns a
    plain explanatory string (not "") when the id is the current session,
    unknown, or empty, so the model always gets actionable feedback rather
    than silence.
    """
    if not target_session_id:
        return "read_session needs a session id (see the other-sessions block)."
    if target_session_id == current_session_id:
        return (
            f"Session {target_session_id} is THIS session — its history is "
            f"already in the conversation above; no need to fetch it."
        )
    turns = state.load_recent_turns(target_session_id, READ_SESSION_TURNS)
    if not turns:
        return f"No session with id {target_session_id} found (or it has no history)."
    blocks = [f"Full recent history of session {target_session_id}:"]
    for turn in turns:
        cwd = turn.get("cwd", "")
        lines = [f"[in {cwd}] request: {turn.get('request', '')}"]
        for step in turn.get("steps", []):
            if step.get("tool") == "run_command" and step.get("rc") is not None:
                command = step.get("args", {}).get("command", "")
                stdout = tools.truncate_for_context(
                    step.get("stdout", ""), tools.COLD_HEAD_CHARS, tools.COLD_TAIL_CHARS
                )
                lines.append(f"  $ {command}  (exit {step.get('rc')})")
                if stdout.strip():
                    lines.append(f"    {stdout.strip()}")
        final = turn.get("final_answer")
        if final:
            lines.append(f"  answer: {final}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_messages(request: str, config: Config, session_id: str) -> list:
    """Assemble the full message list for the first LPU call of a turn.

    Order: system instructions -> current environment -> persistent memory
    -> other-session summaries -> replayed history (last K turns of THIS
    session) -> manual shell history -> the current request. Memory and the
    other-session summaries sit with the ambient setup (context that holds
    for every turn, not tied to any one turn). Crucially THIS session's
    replayed history comes after the other-session summaries and just above
    the request, so an implicit reference ("sort them") resolves against
    this terminal's own turns, while an explicit cross-reference reaches the
    summaries (and read_session) above (Decision 10c; matches the ACDL
    ordering in acdl/v8_multitask.acdl).
    """
    messages = [
        {"role": "system", "content": agent_instructions()},
        {"role": "user", "content": environment_block(config)},
    ]
    if memory := memory_block():
        messages.append({"role": "user", "content": memory})
    if other_sessions := other_sessions_block(session_id):
        messages.append({"role": "user", "content": other_sessions})
    messages.extend(history_messages(session_id))
    if shell_history := user_shell_history_block(session_id):
        messages.append({"role": "user", "content": shell_history})
    messages.append({"role": "user", "content": user_request(request)})
    return messages
