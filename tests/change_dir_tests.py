"""Offline unit tests for change_dir (D1's cd-trap fix, ahead of Phase 7).

These exercise tools.resolve_change_dir (path expansion/validation),
state.write_cd_target/cd_target_path, controller._handle_change_dir, and
the run_turn loop end to end with a scripted fake LPU — no network, no
model, no real subprocess, no real shell wrapper (that's covered by the
live shell tests, see logs/phase6_5/). state.DOIT_HOME is redirected to a
temp dir; llm.call and tools.run_command are stubbed.

Run from the repo root:

    /usr/bin/python3 tests/change_dir_tests.py

Prints a summary and writes logs/phase6_5/change_dir_results.json.
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


def _fresh_session() -> str:
    _fresh_doit_home()
    os.environ["DOIT_SESSION"] = "cd_test"
    return "cd_test"


def _script_llm(decisions) -> None:
    queue = list(decisions)

    def _call(messages, tool_schemas, config, session_id):
        return queue.pop(0)

    llm.call = _call


def _decision(tool, args):
    return llm.Decision(tool_name=tool, args=args, assistant_message={}, tool_call_id=None)


# --- schema ---------------------------------------------------------------

def test_change_dir_in_schema():
    names = {s["function"]["name"] for s in tools.TOOL_SCHEMAS}
    schema = next(s for s in tools.TOOL_SCHEMAS if s["function"]["name"] == "change_dir")
    check("change_dir_in_schema",
          "change_dir" in names
          and schema["function"]["parameters"]["required"] == ["path"],
          f"names={sorted(names)}")


# --- tools.resolve_change_dir ---------------------------------------------

def test_resolve_existing_dir():
    result = tools.resolve_change_dir(str(REPO_ROOT / "doitlib"))
    check("resolve_existing_dir",
          not result.error and result.resolved_path == str(REPO_ROOT / "doitlib"),
          f"result={result}")


def test_resolve_missing_dir_errors():
    result = tools.resolve_change_dir(str(REPO_ROOT / "definitely_missing_xyz"))
    check("resolve_missing_dir_errors",
          bool(result.error) and "no such directory" in result.error,
          f"error={result.error!r}")


def test_resolve_expands_tilde():
    result = tools.resolve_change_dir("~")
    check("resolve_expands_tilde",
          not result.error and result.resolved_path == str(Path.home()),
          f"result={result}")


def test_resolve_relative_path(monkeypatch_cwd=None):
    old_cwd = os.getcwd()
    try:
        os.chdir(REPO_ROOT)
        result = tools.resolve_change_dir("doitlib")
        check("resolve_relative_path",
              not result.error and result.resolved_path == str(REPO_ROOT / "doitlib"),
              f"result={result}")
    finally:
        os.chdir(old_cwd)


# --- state.write_cd_target -------------------------------------------------

def test_write_cd_target_creates_file():
    _fresh_doit_home()
    state.write_cd_target("abc123", "/some/resolved/path")
    path = state.cd_target_path("abc123")
    check("write_cd_target_creates_file",
          path.exists() and path.read_text() == "/some/resolved/path",
          f"path={path}")


# --- controller._handle_change_dir ----------------------------------------

def test_handle_valid_path_writes_target_and_warns_same_turn():
    _fresh_doit_home()
    steps = []
    obs = controller._handle_change_dir({"path": str(REPO_ROOT)}, "sess1", steps)
    target = state.cd_target_path("sess1")
    check("handle_valid_path",
          target.exists() and target.read_text() == str(REPO_ROOT)
          and steps[-1]["resolved_path"] == str(REPO_ROOT)
          and "NOT yet" in obs and str(REPO_ROOT) in obs,
          f"obs={obs!r}")


def test_handle_invalid_path_no_file_written():
    _fresh_doit_home()
    steps = []
    obs = controller._handle_change_dir(
        {"path": str(REPO_ROOT / "nope_xyz")}, "sess1", steps
    )
    target = state.cd_target_path("sess1")
    check("handle_invalid_path_no_file",
          not target.exists() and "error" in steps[-1] and "no such directory" in obs,
          f"obs={obs!r}")


# --- run_turn integration --------------------------------------------------

def test_loop_change_dir_then_answer():
    """change_dir is within-turn: does not consume max_steps, loop continues."""
    session = _fresh_session()
    _script_llm([
        _decision("change_dir", {"path": str(REPO_ROOT / "doitlib")}),
        _decision("answer", {"text": "Done — you'll be in doitlib after this."}),
    ])
    controller.run_turn("go to the doitlib folder", Config(max_steps=1))
    target = state.cd_target_path(session)
    turn = state.load_recent_turns(session, 5)[-1]
    tool_seq = [s["tool"] for s in turn["steps"]]
    check("change_dir_then_answer",
          target.exists() and target.read_text() == str(REPO_ROOT / "doitlib")
          and tool_seq == ["change_dir"]
          and turn["final_answer"].startswith("Done"),
          f"seq={tool_seq}")


def test_loop_change_dir_then_run_command():
    """change_dir first, then the terminal command, in single-command mode."""
    session = _fresh_session()
    ran = {"cmd": None}
    tools.run_command = lambda cmd, shell, timeout: ran.__setitem__("cmd", cmd) or \
        tools.CommandResult(stdout="file1\nfile2\n", stderr="", returncode=0)
    target_dir = str(REPO_ROOT / "doitlib")
    _script_llm([
        _decision("change_dir", {"path": target_dir}),
        _decision("run_command", {"command": f"ls {target_dir}", "is_destructive": False,
                                  "explanation": "list the target directory"}),
    ])
    controller.run_turn("go to doitlib and list it", Config(max_steps=1))
    turn = state.load_recent_turns(session, 5)[-1]
    tool_seq = [s["tool"] for s in turn["steps"]]
    check("change_dir_then_run_command",
          ran["cmd"] == f"ls {target_dir}" and tool_seq == ["change_dir", "run_command"],
          f"seq={tool_seq} cmd={ran['cmd']!r}")


def main() -> int:
    for test in (
        test_change_dir_in_schema,
        test_resolve_existing_dir,
        test_resolve_missing_dir_errors,
        test_resolve_expands_tilde,
        test_resolve_relative_path,
        test_write_cd_target_creates_file,
        test_handle_valid_path_writes_target_and_warns_same_turn,
        test_handle_invalid_path_no_file_written,
        test_loop_change_dir_then_answer,
        test_loop_change_dir_then_run_command,
    ):
        test()

    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    print(f"\n{passed}/{total} passed")

    out_dir = REPO_ROOT / "logs" / "phase6_5"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "change_dir_results.json").write_text(
        json.dumps({"passed": passed, "total": total, "results": results}, indent=2)
    )
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
