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

from . import context, llm, safety, state, tools
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
            blocked_message, observation = _handle_run_command(decision.args, config, steps)
            if blocked_message is not None:
                final_answer = blocked_message
                break
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


def _handle_run_command(args: dict, config: Config, steps: list) -> tuple:
    """Safety-gate and (if allowed) execute one run_command decision.

    Returns (blocked_message, observation). blocked_message is None and
    the turn continues normally when the command ran; otherwise it is
    the text to show the user and the turn ends without executing
    anything (sudo, an interactive program, or a declined confirmation).
    """
    command = args.get("command", "")
    check = safety.check_command(command, args.get("is_destructive", False))

    if check.is_sudo:
        message = f"doit: refusing to run sudo commands. Run it yourself if you're sure:\n    {command}"
        print(message)
        steps.append(_blocked_step(args, "sudo", check))
        return message, None

    if check.is_interactive:
        message = (
            f"doit: '{command}' opens an interactive program doit can't wait "
            f"for. Run it yourself:\n    {command}"
        )
        print(message)
        steps.append(_blocked_step(args, "interactive", check))
        return message, None

    if check.is_destructive and not _confirm_destructive(command, args.get("explanation", "")):
        message = "Aborted. (Nothing was executed.)"
        print(message)
        steps.append(_blocked_step(args, "declined_by_user", check))
        return message, None

    return None, _execute_command(args, config, steps, check)


def _confirm_destructive(command: str, explanation: str) -> bool:
    """Show a destructive command to the user and ask for confirmation.

    Anything other than "y"/"yes" (including a bare Enter) aborts, per
    PLAN.md §3.
    """
    print("⚠ This command modifies the filesystem:")
    print(f"    {command}")
    print(f"  {explanation}")
    answer = input("Proceed? [y/N] ").strip().lower()
    return answer in ("y", "yes")


def _blocked_step(args: dict, reason: str, check: safety.SafetyCheck) -> dict:
    """Build a session-history record for a run_command that did not execute."""
    return {
        "tool": "run_command",
        "args": args,
        "blocked_reason": reason,
        "guard_overrode_model": check.guard_overrode_model,
        "stdout": "",
        "stderr": "",
        "rc": None,
    }


def _execute_command(args: dict, config: Config, steps: list, check: safety.SafetyCheck) -> str:
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
            "guard_overrode_model": check.guard_overrode_model,
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

    Adapter-agnostic: a native decision (tool_call_id set) feeds the
    result back via the provider's tool role; a prompted decision
    (tool_call_id None) has no such role, so the result goes back as a
    plain user message. Only matters when max_steps > 1; with a single
    step the loop ends before the model would see this.
    """
    if not decision.assistant_message:
        return
    messages.append(decision.assistant_message)
    if decision.tool_call_id is not None:
        messages.append(
            {
                "role": "tool",
                "tool_call_id": decision.tool_call_id,
                "content": observation,
            }
        )
    else:
        messages.append({"role": "user", "content": f"Tool result:\n{observation}"})
