"""Offline unit tests for Phase 9: plan(steps[]) + always-on retry (D11).

Exercises tools.tool_schemas_for (the capability gate), controller._handle_plan
(within-turn step, budget bump), and the run_turn loop end to end with a
scripted fake LPU for: a multi-step plan chain, the recovery-stop case (a
plan step finds nothing and the model stops instead of plowing on), the
always-on retry bump after a failed command (both in default single-command
mode and inside a plan), retry firing at most once per turn, a declined
destructive step INSIDE a plan (no free pass), and plans being rejected when
config.enable_plans is False even if a model calls the tool anyway. No
network, no real model, no real subprocess. state.DOIT_HOME is redirected to
a temp dir; llm.call, tools.run_command and builtins.input are stubbed.

Run from the repo root:

    /usr/bin/python3 tests/plan_tests.py

Prints a summary and writes logs/phase9/plan_results.json.
"""

import builtins
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from doitlib import controller, llm, state, tools  # noqa: E402
from doitlib.config import Config  # noqa: E402

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append({"case": name, "pass": bool(ok), "detail": detail})
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def _fresh_doit_home() -> None:
    home = Path(tempfile.mkdtemp())
    state.DOIT_HOME = home
    state.SESSIONS_DIR = home / "sessions"
    state.LOGS_DIR = home / "logs"
    state.MEMORIES_PATH = home / "memories.json"


def _fresh_session(name: str = "plan_test") -> str:
    _fresh_doit_home()
    os.environ["DOIT_SESSION"] = name
    return name


def _script_llm(decisions) -> None:
    queue = list(decisions)

    def _call(messages, tool_schemas, config, session_id):
        return queue.pop(0)

    llm.call = _call


def _decision(tool, args):
    return llm.Decision(tool_name=tool, args=args, assistant_message={}, tool_call_id=None)


def _script_commands(results_by_call):
    """Stub tools.run_command to return CommandResults in order."""
    queue = list(results_by_call)

    def _run(command, shell, timeout):
        return queue.pop(0)

    tools.run_command = _run


def _no_input(*args, **kwargs):
    raise AssertionError("input() should not be called in this test")


def _yes_input(*args, **kwargs):
    return "y"


# --- schema / capability gate ----------------------------------------------

def test_plan_in_schema():
    names = {s["function"]["name"] for s in tools.TOOL_SCHEMAS}
    schema = next(s for s in tools.TOOL_SCHEMAS if s["function"]["name"] == "plan")
    check(
        "plan_in_schema",
        "plan" in names and schema["function"]["parameters"]["required"] == ["steps"],
        f"names={sorted(names)}",
    )


def test_tool_schemas_for_enabled_includes_plan():
    schemas = tools.tool_schemas_for(Config(enable_plans=True))
    names = {s["function"]["name"] for s in schemas}
    check("tool_schemas_for_enabled_includes_plan", "plan" in names, f"names={sorted(names)}")


def test_tool_schemas_for_disabled_excludes_plan():
    schemas = tools.tool_schemas_for(Config(enable_plans=False))
    names = {s["function"]["name"] for s in schemas}
    check(
        "tool_schemas_for_disabled_excludes_plan",
        "plan" not in names and len(schemas) == len(tools.TOOL_SCHEMAS) - 1,
        f"names={sorted(names)}",
    )


# --- controller._handle_plan -------------------------------------------------

def test_handle_plan_bumps_budget():
    steps = []
    obs, new_budget = controller._handle_plan(
        {"steps": ["find the files", "show them", "compress them"]},
        Config(enable_plans=True, max_steps=1),
        1,
        steps,
    )
    expected = 3 + controller.PLAN_SLACK
    check(
        "handle_plan_bumps_budget",
        new_budget == expected and steps[-1]["tool"] == "plan" and "Plan noted" in obs,
        f"new_budget={new_budget} expected={expected} obs={obs!r}",
    )


def test_handle_plan_disabled_rejected():
    steps = []
    obs, new_budget = controller._handle_plan(
        {"steps": ["a", "b"]}, Config(enable_plans=False, max_steps=1), 1, steps
    )
    check(
        "handle_plan_disabled_rejected",
        new_budget == 1 and steps[-1].get("rejected") == "plans_disabled"
        and "not available" in obs,
        f"new_budget={new_budget} obs={obs!r} steps={steps}",
    )


def test_handle_plan_empty_steps_noop():
    steps = []
    obs, new_budget = controller._handle_plan(
        {"steps": []}, Config(enable_plans=True, max_steps=1), 1, steps
    )
    check(
        "handle_plan_empty_steps_noop",
        new_budget == 1 and "error" in steps[-1],
        f"new_budget={new_budget} obs={obs!r}",
    )


def test_handle_plan_caps_at_max_plan_steps():
    steps = []
    many = [f"step {i}" for i in range(controller.MAX_PLAN_STEPS + 5)]
    obs, new_budget = controller._handle_plan(
        {"steps": many}, Config(enable_plans=True, max_steps=1), 1, steps
    )
    recorded = steps[-1]["args"]["steps"]
    check(
        "handle_plan_caps_at_max_plan_steps",
        len(recorded) == controller.MAX_PLAN_STEPS
        and new_budget == controller.MAX_PLAN_STEPS + controller.PLAN_SLACK,
        f"len(recorded)={len(recorded)} new_budget={new_budget}",
    )


def test_handle_plan_never_shrinks_budget():
    """A plan shorter than an already-bumped budget must not lower it."""
    steps = []
    obs, new_budget = controller._handle_plan(
        {"steps": ["one step"]}, Config(enable_plans=True, max_steps=1), 10, steps
    )
    check("handle_plan_never_shrinks_budget", new_budget == 10, f"new_budget={new_budget}")


# --- run_turn integration: multi-step plan chain ----------------------------

def test_loop_plan_chain_feeds_forward():
    """plan() then 2 run_commands (using each real output), then answer.

    "answer" is always the finish signal (ends the turn unconditionally),
    so it must come LAST in the scripted sequence, after every command —
    never in the middle of a plan.
    """
    session = _fresh_session()
    _script_commands([
        tools.CommandResult(stdout="run3.log\n", stderr="", returncode=0),
        tools.CommandResult(stdout="run3.log.gz\n", stderr="", returncode=0),
    ])
    _script_llm([
        _decision("plan", {"steps": ["find the log", "show it", "gzip it"]}),
        _decision("run_command", {
            "command": "find . -name '*.log'", "is_destructive": False,
            "explanation": "find log files",
        }),
        _decision("run_command", {
            "command": "gzip run3.log", "is_destructive": True,
            "explanation": "compress the log found above",
        }),
        _decision("answer", {"text": "Found run3.log and compressed it."}),
    ])
    builtins.input = _yes_input
    controller.run_turn(
        "find the log and compress it", Config(max_steps=1, enable_plans=True)
    )
    turn = state.load_recent_turns(session, 5)[-1]
    tool_seq = [s["tool"] for s in turn["steps"]]
    check(
        "loop_plan_chain_feeds_forward",
        tool_seq == ["plan", "run_command", "run_command"]
        and turn["final_answer"] == "Found run3.log and compressed it.",
        f"seq={tool_seq} final_answer={turn['final_answer']!r}",
    )


def test_loop_plan_recovery_stop():
    """A plan step that finds nothing -> model answers instead of plowing on."""
    session = _fresh_session()
    _script_commands([
        tools.CommandResult(stdout="", stderr="", returncode=0),
    ])
    _script_llm([
        _decision("plan", {"steps": ["find *.log under ~/projects", "compress them"]}),
        _decision("run_command", {
            "command": "find ~/projects -name '*.log'", "is_destructive": False,
            "explanation": "search for log files",
        }),
        _decision("answer", {"text": "No .log files found under ~/projects — nothing to compress."}),
    ])
    controller.run_turn("compress the largest logs under ~/projects", Config(max_steps=1, enable_plans=True))
    turn = state.load_recent_turns(session, 5)[-1]
    tool_seq = [s["tool"] for s in turn["steps"]]
    check(
        "loop_plan_recovery_stop",
        tool_seq == ["plan", "run_command"] and "No .log files" in turn["final_answer"],
        f"seq={tool_seq} answer={turn['final_answer']!r}",
    )


def test_loop_plan_destructive_step_still_gated():
    """A destructive step inside a plan still hits the y/N gate; decline aborts."""
    session = _fresh_session()

    def _no(*a, **k):
        return "n"

    builtins.input = _no
    _script_llm([
        _decision("plan", {"steps": ["list junk files", "delete them"]}),
        _decision("run_command", {
            "command": "rm junk.txt", "is_destructive": True,
            "explanation": "delete the junk file",
        }),
    ])
    controller.run_turn("delete junk.txt after listing it", Config(max_steps=1, enable_plans=True))
    turn = state.load_recent_turns(session, 5)[-1]
    check(
        "loop_plan_destructive_step_still_gated",
        turn["final_answer"] == "Aborted. (Nothing was executed.)"
        and turn["steps"][-1]["blocked_reason"] == "declined_by_user",
        f"turn={turn}",
    )


# --- run_turn integration: always-on retry ----------------------------------

def test_loop_retry_after_failure_default_single_command():
    """Default max_steps=1: a failing command still gets ONE corrective retry."""
    session = _fresh_session()
    _script_commands([
        tools.CommandResult(stdout="", stderr="no such file\n", returncode=1),
        tools.CommandResult(stdout="ok\n", stderr="", returncode=0),
    ])
    _script_llm([
        _decision("run_command", {
            "command": "cat missing.txt", "is_destructive": False,
            "explanation": "show the file",
        }),
        _decision("run_command", {
            "command": "cat existing.txt", "is_destructive": False,
            "explanation": "show the correct file instead",
        }),
    ])
    controller.run_turn("show me the file", Config(max_steps=1, enable_plans=True))
    turn = state.load_recent_turns(session, 5)[-1]
    tool_seq = [s["tool"] for s in turn["steps"]]
    rcs = [s.get("rc") for s in turn["steps"] if s["tool"] == "run_command"]
    # the retry lets the model try again after the failure, but the turn
    # ends the moment the (now-exhausted) budget is hit again -- there is
    # no room for a trailing "answer" here, same as single-command mode
    # never gets one after its one command; the printed stdout IS the
    # user-facing result.
    check(
        "loop_retry_after_failure_default_single_command",
        tool_seq == ["run_command", "run_command"] and rcs == [1, 0],
        f"seq={tool_seq} rcs={rcs}",
    )


def test_loop_no_retry_when_command_succeeds():
    """max_steps=1, success on the first try: no retry, turn ends after one command."""
    session = _fresh_session()
    _script_commands([tools.CommandResult(stdout="ok\n", stderr="", returncode=0)])
    _script_llm([
        _decision("run_command", {
            "command": "ls", "is_destructive": False, "explanation": "list files",
        }),
    ])
    controller.run_turn("list files", Config(max_steps=1, enable_plans=True))
    turn = state.load_recent_turns(session, 5)[-1]
    tool_seq = [s["tool"] for s in turn["steps"]]
    check("loop_no_retry_when_command_succeeds", tool_seq == ["run_command"], f"seq={tool_seq}")


def test_loop_retry_fires_at_most_once():
    """Two consecutive failures at the budget boundary: only one retry is granted."""
    session = _fresh_session()
    _script_commands([
        tools.CommandResult(stdout="", stderr="err1\n", returncode=1),
        tools.CommandResult(stdout="", stderr="err2\n", returncode=1),
    ])
    _script_llm([
        _decision("run_command", {
            "command": "cat a.txt", "is_destructive": False, "explanation": "try a",
        }),
        _decision("run_command", {
            "command": "cat b.txt", "is_destructive": False, "explanation": "try b",
        }),
    ])
    controller.run_turn("show me the file", Config(max_steps=1, enable_plans=True))
    turn = state.load_recent_turns(session, 5)[-1]
    tool_seq = [s["tool"] for s in turn["steps"]]
    check(
        "loop_retry_fires_at_most_once",
        tool_seq == ["run_command", "run_command"] and turn["final_answer"] is None,
        f"seq={tool_seq} final_answer={turn['final_answer']!r}",
    )


def test_loop_retry_inside_plan_does_not_double_grant():
    """A plan's own budget already covers a mid-plan failure -- retry only adds
    slack when a failure happens right at the (possibly plan-raised) boundary."""
    session = _fresh_session()
    _script_commands([
        tools.CommandResult(stdout="a.log\n", stderr="", returncode=0),
        tools.CommandResult(stdout="", stderr="permission denied\n", returncode=1),
        tools.CommandResult(stdout="a.log.gz\n", stderr="", returncode=0),
    ])
    _script_llm([
        _decision("plan", {"steps": ["find logs", "gzip them"]}),
        _decision("run_command", {
            "command": "find . -name '*.log'", "is_destructive": False,
            "explanation": "find logs",
        }),
        _decision("run_command", {
            "command": "gzip a.log", "is_destructive": True, "explanation": "compress",
        }),
        _decision("run_command", {
            "command": "sudo gzip a.log", "is_destructive": True,
            "explanation": "retry with elevated perms",
        }),
    ])
    builtins.input = _yes_input
    controller.run_turn("find and gzip the logs", Config(max_steps=1, enable_plans=True))
    turn = state.load_recent_turns(session, 5)[-1]
    tool_seq = [s["tool"] for s in turn["steps"]]
    # find -> gzip (fails, rc=1, but budget=2+PLAN_SLACK has room) -> continues
    # -> sudo gzip is hard-refused (never executes) -> turn ends there.
    check(
        "loop_retry_inside_plan_does_not_double_grant",
        tool_seq == ["plan", "run_command", "run_command", "run_command"]
        and turn["steps"][-1]["blocked_reason"] == "sudo",
        f"seq={tool_seq} last={turn['steps'][-1]}",
    )


def test_loop_plan_rejected_when_disabled_falls_back_to_single_command():
    """A model that hallucinates plan() with enable_plans=False gets refused,
    then still only has the default 1-command budget (no retry needed here
    since the model changes its mind and answers instead)."""
    session = _fresh_session()
    _script_llm([
        _decision("plan", {"steps": ["a", "b", "c"]}),
        _decision("answer", {"text": "Plans aren't available; here's the single command result instead."}),
    ])
    controller.run_turn("do several things", Config(max_steps=1, enable_plans=False))
    turn = state.load_recent_turns(session, 5)[-1]
    tool_seq = [s["tool"] for s in turn["steps"]]
    check(
        "loop_plan_rejected_when_disabled",
        tool_seq == ["plan"] and turn["steps"][0].get("rejected") == "plans_disabled",
        f"seq={tool_seq} steps={turn['steps']}",
    )


def main() -> int:
    for test in (
        test_plan_in_schema,
        test_tool_schemas_for_enabled_includes_plan,
        test_tool_schemas_for_disabled_excludes_plan,
        test_handle_plan_bumps_budget,
        test_handle_plan_disabled_rejected,
        test_handle_plan_empty_steps_noop,
        test_handle_plan_caps_at_max_plan_steps,
        test_handle_plan_never_shrinks_budget,
        test_loop_plan_chain_feeds_forward,
        test_loop_plan_recovery_stop,
        test_loop_plan_destructive_step_still_gated,
        test_loop_retry_after_failure_default_single_command,
        test_loop_no_retry_when_command_succeeds,
        test_loop_retry_fires_at_most_once,
        test_loop_retry_inside_plan_does_not_double_grant,
        test_loop_plan_rejected_when_disabled_falls_back_to_single_command,
    ):
        test()

    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    print(f"\n{passed}/{total} passed")

    out_dir = REPO_ROOT / "logs" / "phase9"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plan_results.json").write_text(
        json.dumps({"passed": passed, "total": total, "results": results}, indent=2)
    )
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
