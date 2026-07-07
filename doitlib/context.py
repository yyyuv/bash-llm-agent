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

from .config import Config, resolve_shell

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


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


def build_messages(request: str, config: Config) -> list:
    """Assemble the full message list for the first LPU call of a turn."""
    return [
        {"role": "system", "content": agent_instructions()},
        {"role": "user", "content": environment_block(config)},
        {"role": "user", "content": user_request(request)},
    ]
