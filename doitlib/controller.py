"""The agentic loop.

build context -> ask the LPU for a Decision -> dispatch the chosen tool
-> feed the result back -> repeat until `answer` or the step cap.

With max_steps=1 (Phase 1) this degenerates to single-command mode: one
decision, carried out, done. Every turn is recorded in the session
history under ~/.doit/sessions/.
"""

import os
import sys
import time

from . import context, llm, state, tools
from .config import Config, resolve_shell


def run_turn(request: str, config: Config) -> None:
    """Handle one user request end to end, printing output as we go."""
    session_id = state.get_session_id()
    messages = context.build_messages(request, config)
    steps = []
    final_answer = None

    for _ in range(config.max_steps):
        decision = llm.call(messages, tools.TOOL_SCHEMAS, config, session_id)

        if decision.tool_name == "answer":
            final_answer = decision.args.get("text", "")
            print(final_answer)
            break

        if decision.tool_name == "run_command":
            observation = _execute_command(decision.args, config, steps)
        else:
            observation = f"unknown tool: {decision.tool_name}"
            print(f"doit: model chose an unknown tool ({decision.tool_name})", file=sys.stderr)
            steps.append({"tool": decision.tool_name, "args": decision.args})

        _append_tool_result(messages, decision, observation)

    state.record_turn(
        session_id,
        {
            "ts": time.time(),
            "cwd": os.getcwd(),
            "request": request,
            "steps": steps,
            "final_answer": final_answer,
        },
    )


def _execute_command(args: dict, config: Config, steps: list) -> str:
    """Run one run_command decision, print its output, record the step.

    Returns the (truncated) observation text to feed back to the LPU.
    """
    command = args.get("command", "")
    print(f"$ {command}", file=sys.stderr)
    result = tools.run_command(
        command, resolve_shell(config), config.command_timeout_seconds
    )

    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
    if result.returncode != 0:
        print(f"doit: command exited with code {result.returncode}", file=sys.stderr)

    steps.append(
        {
            "tool": "run_command",
            "args": args,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "rc": result.returncode,
        }
    )
    return (
        f"exit code: {result.returncode}\n"
        f"stdout:\n{tools.truncate_for_context(result.stdout)}\n"
        f"stderr:\n{tools.truncate_for_context(result.stderr)}"
    )


def _append_tool_result(messages: list, decision: llm.Decision, observation: str) -> None:
    """Feed a tool's result back into the conversation for the next step.

    Only matters when max_steps > 1; with a single step the loop ends
    before the model would see this.
    """
    if decision.assistant_message:
        messages.append(decision.assistant_message)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": decision.tool_call_id,
                "content": observation,
            }
        )
