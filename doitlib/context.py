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
from pathlib import Path

from . import state, tools
from .config import Config, resolve_shell

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# K: replay at most the last K prior turns of this session as context
# (PLAN.md Phase 4). Older turns are dropped for now; a Phase 9 extension
# would summarize them instead.
HISTORY_TURNS = 10


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


def build_messages(request: str, config: Config, session_id: str) -> list:
    """Assemble the full message list for the first LPU call of a turn.

    Order: system instructions -> current environment -> replayed history
    (last K turns) -> the current request. History sits between the
    ambient setup and the new request so a reference in the request
    resolves against the turns just above it.
    """
    messages = [
        {"role": "system", "content": agent_instructions()},
        {"role": "user", "content": environment_block(config)},
    ]
    messages.extend(history_messages(session_id))
    messages.append({"role": "user", "content": user_request(request)})
    return messages
