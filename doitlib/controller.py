"""The agentic loop.

build context -> ask the LPU for a Decision -> dispatch the chosen tool
-> feed the result back -> repeat until `answer` or the step cap.

With max_steps=1 (Phase 1) this degenerates to single-command mode: one
decision, carried out, done. Every turn is recorded in the session
history under ~/.doit/sessions/.

Phase 4 makes turns multi-turn aware: build_messages replays this
session's last K turns into the context (context.history_messages), so a
follow-up like "now sort them by date" resolves against the previous
turn. The within-turn loop is unchanged; single-command mode still means
one command per turn.

Phase 5 adds the `ask_user` tool: when the model needs to clarify, the
controller prints the question, blocks on input(), feeds the reply back,
and re-calls the model — all inside the same turn. A clarification is NOT
a command step: it doesn't count against max_steps. To keep doit from
nagging, at most MAX_CLARIFICATIONS questions are asked per turn; past
that the model is told to proceed with its best assumption (Section 6).
"""

import os
import sys
import time

from . import context, llm, safety, state, tools
from .config import Config, resolve_shell

# Structural non-annoyance cap (PLAN §6 / Section 6): a single turn may ask
# at most this many clarifying questions. Enforced in code, not just via the
# prompt — beyond it the model is forced to act on its best interpretation.
MAX_CLARIFICATIONS = 2


def run_turn(request: str, config: Config) -> None:
    """Handle one user request end to end, printing output as we go."""
    session_id = state.get_session_id()
    messages = context.build_messages(request, config, session_id)
    steps = []
    final_answer = None
    clarifications = 0
    command_steps = 0

    # Loop guard: max_steps command steps + the clarification budget + a little
    # slack, so a model that never converges still terminates cleanly.
    for _ in range(config.max_steps + MAX_CLARIFICATIONS + 1):
        decision = llm.call(messages, tools.TOOL_SCHEMAS, config, session_id)

        if decision.tool_name == "answer":
            final_answer = decision.args.get("text", "")
            print(final_answer)
            break

        if decision.tool_name == "ask_user":
            observation, aborted = _handle_ask_user(decision.args, clarifications, steps)
            if aborted is not None:
                final_answer = aborted
                break
            clarifications += 1
            _append_tool_result(messages, decision, observation)
            continue

        if decision.tool_name == "run_command":
            blocked_message, observation = _handle_run_command(decision.args, config, steps)
            if blocked_message is not None:
                final_answer = blocked_message
                break
            command_steps += 1
            if command_steps >= config.max_steps:
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


def _handle_ask_user(args: dict, clarifications: int, steps: list) -> tuple:
    """Resolve one ask_user decision within the same turn.

    Returns (observation, aborted). observation is fed back to the model as
    the tool's result; aborted is None to continue the turn, or the final
    message when the turn should end.

    Non-annoyance cap: once MAX_CLARIFICATIONS questions have been asked we
    stop bothering the user and tell the model to commit to its best guess.

    Unanswered input (DECISION 8, option a): a bare Enter or EOF (Ctrl-D /
    no stdin) means "no answer" — we tell the model to proceed with the
    default it stated. Safety is not weakened: if that default leads to a
    destructive command, the run_command confirmation still requires an
    explicit "y". Ctrl-C is the conventional "stop" and aborts the turn.
    """
    question = args.get("question", "")
    options = args.get("options") or []

    if clarifications >= MAX_CLARIFICATIONS:
        steps.append({"tool": "ask_user", "args": args, "clarification_capped": True})
        return (
            "You have reached the clarification limit — do not call ask_user "
            "again. Pick the most reasonable interpretation, act on it, and "
            "state the assumption you made.",
            None,
        )

    try:
        reply = _prompt_user(question, options)
    except KeyboardInterrupt:
        message = "\nAborted. (Nothing was executed.)"
        print(message)
        steps.append({"tool": "ask_user", "args": args, "reply": None, "aborted": True})
        return "", message

    steps.append({"tool": "ask_user", "args": args, "reply": reply})
    if reply == "":
        return (
            "The user gave no answer. Proceed with the most sensible default "
            "and state the assumption you made in your final answer.",
            None,
        )
    return f"The user answered: {reply}", None


def _prompt_user(question: str, options: list) -> str:
    """Print a clarifying question (+ numbered options) and read one reply.

    When options are given and the user types a number, it is resolved to
    that option's text so the model gets the choice, not the digit. A bare
    Enter or EOF returns "" (the "no answer" default path).
    """
    print(question)
    for index, option in enumerate(options, 1):
        print(f"  {index}. {option}")
    prompt = "Your answer (number or text): " if options else "Your answer: "
    try:
        reply = input(prompt).strip()
    except EOFError:
        return ""
    if options and reply.isdigit():
        choice = int(reply)
        if 1 <= choice <= len(options):
            return options[choice - 1]
    return reply


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
