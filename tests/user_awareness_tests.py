"""Offline unit tests for Phase 7 user awareness (the shell-history hook).

These exercise state.load_recent_user_commands (parsing ts|cwd|cmd lines,
filtering out doit's own invocations, the missing-file/malformed-line/limit
edge cases) and context.user_shell_history_block + build_messages (the
labeled block, the empty case, and where it sits in the message list) — no
network, no model, no real shell. state.SHELL_HIST_DIR is redirected to a
temp dir per test.

Run from the repo root (no litellm needed, but any python3 works):

    /usr/bin/python3 tests/user_awareness_tests.py

Prints a summary and writes logs/phase7/user_awareness_results.json.
"""

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from doitlib import context, state  # noqa: E402
from doitlib.config import Config  # noqa: E402

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append({"case": name, "pass": bool(ok), "detail": detail})
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def _fresh_shell_hist() -> str:
    """Point SHELL_HIST_DIR at a brand-new temp dir; return a session id."""
    state.SHELL_HIST_DIR = Path(tempfile.mkdtemp())
    return "hist_test"


def _write_hist(session_id: str, lines: list) -> None:
    path = state.SHELL_HIST_DIR / session_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


# --- state.load_recent_user_commands --------------------------------------

def test_missing_file_yields_empty():
    session = _fresh_shell_hist()
    check("missing_file_empty", state.load_recent_user_commands(session, 20) == [])


def test_parses_ts_cwd_cmd_lines():
    session = _fresh_shell_hist()
    _write_hist(session, [
        "1730001000|/home/yuval|cd ~/school/llms/ass3",
        "1730001005|/home/yuval/school/llms/ass3|mkdir data",
        "1730001010|/home/yuval/school/llms/ass3|python train.py",
    ])
    commands = state.load_recent_user_commands(session, 20)
    check("parses_lines",
          [c["cmd"] for c in commands] == ["cd ~/school/llms/ass3", "mkdir data", "python train.py"]
          and commands[0]["cwd"] == "/home/yuval"
          and commands[0]["ts"] == "1730001000",
          f"commands={commands}")


def test_filters_out_doit_invocations():
    session = _fresh_shell_hist()
    _write_hist(session, [
        "1|/tmp|mkdir data",
        '2|/tmp|doit "make a data folder"',
        "3|/tmp|doit",
        "4|/tmp|ls -la",
    ])
    commands = [c["cmd"] for c in state.load_recent_user_commands(session, 20)]
    check("filters_doit",
          commands == ["mkdir data", "ls -la"],
          f"commands={commands}")


def test_skips_malformed_lines():
    session = _fresh_shell_hist()
    _write_hist(session, [
        "not a valid line at all",
        "1|/tmp|",  # empty command is still 3 fields, kept
        "2|/tmp|echo hi",
        "",
    ])
    commands = [c["cmd"] for c in state.load_recent_user_commands(session, 20)]
    check("skips_malformed",
          commands == ["", "echo hi"],
          f"commands={commands}")


def test_limit_keeps_most_recent():
    session = _fresh_shell_hist()
    _write_hist(session, [f"{i}|/tmp|cmd{i}" for i in range(30)])
    commands = [c["cmd"] for c in state.load_recent_user_commands(session, 5)]
    check("limit_keeps_recent",
          commands == [f"cmd{i}" for i in range(25, 30)],
          f"commands={commands}")


def test_session_isolation():
    """One terminal's shell_hist file must not leak into another's."""
    state.SHELL_HIST_DIR = Path(tempfile.mkdtemp())
    _write_hist("session_a", ["1|/tmp|echo a"])
    _write_hist("session_b", ["1|/tmp|echo b"])
    a = [c["cmd"] for c in state.load_recent_user_commands("session_a", 20)]
    b = [c["cmd"] for c in state.load_recent_user_commands("session_b", 20)]
    check("session_isolation", a == ["echo a"] and b == ["echo b"], f"a={a} b={b}")


# --- context.user_shell_history_block --------------------------------------

def test_block_empty_when_no_history():
    session = _fresh_shell_hist()
    check("block_empty", context.user_shell_history_block(session) == "")


def test_block_labels_commands_with_cwd():
    session = _fresh_shell_hist()
    _write_hist(session, [
        "1|/home/yuval|cd ~/school/llms/ass3",
        "2|/home/yuval/school/llms/ass3|mkdir data",
    ])
    block = context.user_shell_history_block(session)
    check("block_labels",
          "[in /home/yuval] cd ~/school/llms/ass3" in block
          and "[in /home/yuval/school/llms/ass3] mkdir data" in block
          and "manually" in block.lower(),
          f"block={block!r}")


def test_build_messages_injects_block_only_when_nonempty():
    session = _fresh_shell_hist()
    state.SESSIONS_DIR = Path(tempfile.mkdtemp())
    state.MEMORIES_PATH = Path(tempfile.mkdtemp()) / "memories.json"
    without = context.build_messages("hi", Config(), session)
    _write_hist(session, ["1|/tmp/proj|python train.py"])
    with_hist = context.build_messages("hi", Config(), session)
    joined_without = " ".join(m["content"] for m in without)
    joined_with = " ".join(m["content"] for m in with_hist)
    check("build_injects_block",
          "python train.py" not in joined_without
          and "python train.py" in joined_with
          and len(with_hist) == len(without) + 1,
          f"lens={len(without)}->{len(with_hist)}")


def test_block_sits_before_request():
    """The shell-history block must precede the current request message."""
    session = _fresh_shell_hist()
    state.SESSIONS_DIR = Path(tempfile.mkdtemp())
    state.MEMORIES_PATH = Path(tempfile.mkdtemp()) / "memories.json"
    _write_hist(session, ["1|/tmp/proj|python train.py"])
    messages = context.build_messages("summarize what I just did", Config(), session)
    contents = [m["content"] for m in messages]
    hist_index = next(i for i, c in enumerate(contents) if "python train.py" in c)
    request_index = next(i for i, c in enumerate(contents) if c == "summarize what I just did")
    check("block_before_request", hist_index < request_index,
          f"hist_index={hist_index} request_index={request_index}")


def main() -> int:
    for test in (
        test_missing_file_yields_empty,
        test_parses_ts_cwd_cmd_lines,
        test_filters_out_doit_invocations,
        test_skips_malformed_lines,
        test_limit_keeps_most_recent,
        test_session_isolation,
        test_block_empty_when_no_history,
        test_block_labels_commands_with_cwd,
        test_build_messages_injects_block_only_when_nonempty,
        test_block_sits_before_request,
    ):
        test()

    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    print(f"\n{passed}/{total} passed")

    out_dir = REPO_ROOT / "logs" / "phase7"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "user_awareness_results.json").write_text(
        json.dumps({"passed": passed, "total": total, "results": results}, indent=2)
    )
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
