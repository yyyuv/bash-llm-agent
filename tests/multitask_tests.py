"""Offline unit tests for Phase 8 multi-tasking (Decision 10c).

These exercise the always-injected other-session summaries and the
read_session fetch tool, without network or a real model:
 - state.list_other_sessions (excludes current, most-recent-first, recency
   filter, per-session request cap, max_sessions cap);
 - context.other_sessions_block (header, ids/cwd/requests, empty case);
 - context.render_session_detail (real transcript, self/unknown/empty id);
 - build_messages (block injected only when other sessions exist, and the
   ordering that keeps implicit references local);
 - controller._handle_read_session + run_turn end to end with a scripted
   fake LPU (read another session, then act on it in the same turn).

state.SESSIONS_DIR / MEMORIES_PATH / SHELL_HIST_DIR are redirected to temp
dirs; llm.call and tools.run_command are stubbed.

Run from the repo root:

    /usr/bin/python3 tests/multitask_tests.py

Prints a summary and writes logs/phase8/multitask_results.json.
"""

import builtins
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from doitlib import context, controller, llm, state, tools  # noqa: E402
from doitlib.config import Config  # noqa: E402

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append({"case": name, "pass": bool(ok), "detail": detail})
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def _fresh_state() -> None:
    """Redirect every ~/.doit path this phase touches to fresh temp dirs."""
    home = Path(tempfile.mkdtemp())
    state.DOIT_HOME = home
    state.SESSIONS_DIR = home / "sessions"
    state.LOGS_DIR = home / "logs"
    state.MEMORIES_PATH = home / "memories.json"
    state.SHELL_HIST_DIR = home / "shell_hist"


def _write_session(session_id: str, turns: list) -> None:
    """Write turn records straight to a session's JSONL file."""
    for turn in turns:
        state.record_turn(session_id, turn)


def _turn(request, cwd="/tmp", ts=None, command=None, rc=0, stdout="", answer=None):
    steps = []
    if command is not None:
        steps.append({"tool": "run_command", "args": {"command": command},
                      "stdout": stdout, "stderr": "", "rc": rc})
    return {"ts": ts if ts is not None else time.time(), "cwd": cwd,
            "request": request, "steps": steps, "final_answer": answer}


def _script_llm(decisions) -> None:
    queue = list(decisions)

    def _call(messages, tool_schemas, config, session_id):
        return queue.pop(0)

    llm.call = _call


def _decision(tool, args):
    return llm.Decision(tool_name=tool, args=args, assistant_message={}, tool_call_id=None)


# --- schema ---------------------------------------------------------------

def test_read_session_in_schema():
    names = {s["function"]["name"] for s in tools.TOOL_SCHEMAS}
    rs = next(s for s in tools.TOOL_SCHEMAS if s["function"]["name"] == "read_session")
    check("read_session_in_schema",
          "read_session" in names
          and rs["function"]["parameters"]["required"] == ["session_id"],
          f"names={sorted(names)}")


# --- state.list_other_sessions --------------------------------------------

def test_excludes_current_session():
    _fresh_state()
    _write_session("me", [_turn("list files")])
    _write_session("other", [_turn("make folders")])
    others = state.list_other_sessions("me")
    check("excludes_current",
          [s["id"] for s in others] == ["other"],
          f"ids={[s['id'] for s in others]}")


def test_most_recent_first():
    _fresh_state()
    now = time.time()
    _write_session("old", [_turn("old task", ts=now - 500)])
    _write_session("new", [_turn("new task", ts=now - 10)])
    ids = [s["id"] for s in state.list_other_sessions("me")]
    check("most_recent_first", ids == ["new", "old"], f"ids={ids}")


def test_recency_filter_drops_stale():
    _fresh_state()
    now = time.time()
    _write_session("fresh", [_turn("fresh", ts=now - 60)])
    _write_session("stale", [_turn("stale", ts=now - (48 * 3600))])
    ids = [s["id"] for s in state.list_other_sessions("me")]
    check("recency_filter", ids == ["fresh"], f"ids={ids}")


def test_summary_keeps_last_requests_and_cwd():
    _fresh_state()
    _write_session("s1", [
        _turn("first", cwd="/home/x"),
        _turn("second", cwd="/home/x"),
        _turn("third", cwd="/home/y"),
    ])
    s = state.list_other_sessions("me")[0]
    # requests_per_session default is 2 -> the last two requests, cwd from last turn
    check("summary_content",
          s["requests"] == ["second", "third"] and s["cwd"] == "/home/y",
          f"summary={s}")


def test_max_sessions_cap():
    _fresh_state()
    now = time.time()
    for i in range(8):
        _write_session(f"s{i}", [_turn(f"task{i}", ts=now - i)])
    others = state.list_other_sessions("me", max_sessions=3)
    check("max_sessions_cap", len(others) == 3, f"n={len(others)}")


def test_empty_when_only_current():
    _fresh_state()
    _write_session("me", [_turn("only mine")])
    check("empty_when_alone", state.list_other_sessions("me") == [])


# --- context.other_sessions_block -----------------------------------------

def test_block_empty_when_no_others():
    _fresh_state()
    _write_session("me", [_turn("mine")])
    check("block_empty", context.other_sessions_block("me") == "")


def test_block_lists_id_cwd_requests():
    _fresh_state()
    _write_session("f4a2", [_turn("create a folder for each year 2020 to 2026", cwd="/home/docs")])
    block = context.other_sessions_block("me")
    check("block_lists",
          "session f4a2" in block
          and "/home/docs" in block
          and "create a folder for each year 2020 to 2026" in block
          and "other" in block.lower(),
          f"block={block!r}")


# --- context.render_session_detail ----------------------------------------

def test_detail_renders_commands_and_answer():
    _fresh_state()
    _write_session("f4a2", [
        _turn("create folders", cwd="/home/docs",
              command="mkdir 2020 2021 2022", rc=0, stdout="",
              answer="Created folders 2020-2022."),
    ])
    detail = context.render_session_detail("f4a2", "me")
    check("detail_content",
          "f4a2" in detail
          and "mkdir 2020 2021 2022" in detail
          and "Created folders 2020-2022." in detail
          and "/home/docs" in detail,
          f"detail={detail!r}")


def test_detail_self_is_rejected():
    _fresh_state()
    _write_session("me", [_turn("mine")])
    detail = context.render_session_detail("me", "me")
    check("detail_self",
          "THIS session" in detail and "mkdir" not in detail,
          f"detail={detail!r}")


def test_detail_unknown_and_empty():
    _fresh_state()
    unknown = context.render_session_detail("nope", "me")
    empty = context.render_session_detail("", "me")
    check("detail_unknown_empty",
          "No session" in unknown and "needs a session id" in empty,
          f"unknown={unknown!r} empty={empty!r}")


# --- build_messages ordering ----------------------------------------------

def test_build_injects_block_only_with_others():
    _fresh_state()
    os.environ["DOIT_SESSION"] = "me"
    without = context.build_messages("hi", Config(), "me")
    _write_session("other", [_turn("make folders 2020-2026")])
    with_other = context.build_messages("hi", Config(), "me")
    joined_without = " ".join(m["content"] for m in without)
    joined_with = " ".join(m["content"] for m in with_other)
    check("build_injects_block",
          "make folders 2020-2026" not in joined_without
          and "make folders 2020-2026" in joined_with
          and len(with_other) == len(without) + 1,
          f"lens={len(without)}->{len(with_other)}")


def test_other_sessions_before_own_history_and_request():
    """Ordering is what keeps implicit references local: other-session
    summaries must come BEFORE this session's own replayed history, which
    in turn comes before the current request."""
    _fresh_state()
    _write_session("other", [_turn("OTHER window folder task")])
    _write_session("me", [_turn("MY listing here", answer="listed files")])
    messages = context.build_messages("sort them by date", Config(), "me")
    contents = [m["content"] for m in messages]
    other_i = next(i for i, c in enumerate(contents) if "OTHER window folder task" in c)
    own_i = next(i for i, c in enumerate(contents) if "MY listing here" in c)
    req_i = next(i for i, c in enumerate(contents) if c == "sort them by date")
    check("ordering",
          other_i < own_i < req_i,
          f"other={other_i} own={own_i} req={req_i}")


# --- controller integration -----------------------------------------------

def test_handle_read_session_returns_detail_and_records():
    _fresh_state()
    _write_session("f4a2", [_turn("create folders", command="mkdir 2020", answer="done")])
    steps = []
    obs = controller._handle_read_session({"session_id": "f4a2"}, "me", steps)
    check("handle_read_session",
          "mkdir 2020" in obs and steps[-1]["tool"] == "read_session"
          and steps[-1]["args"]["session_id"] == "f4a2",
          f"obs={obs!r}")


def test_loop_read_then_run_command():
    """The cross-reference case end to end: the model reads another session,
    then reproduces its task here — read_session then run_command, one turn."""
    _fresh_state()
    os.environ["DOIT_SESSION"] = "me"
    _write_session("f4a2", [_turn("create folders 2020-2026",
                                  command="mkdir 2020 2021 2022 2023 2024 2025 2026",
                                  answer="Created year folders.")])
    ran = {"cmd": None}
    tools.run_command = lambda cmd, shell, timeout: ran.__setitem__("cmd", cmd) or \
        tools.CommandResult(stdout="", stderr="", returncode=0)
    _script_llm([
        _decision("read_session", {"session_id": "f4a2"}),
        _decision("run_command", {"command": "mkdir 2020 2021 2022 2023 2024 2025 2026",
                                  "is_destructive": True, "explanation": "recreate year folders"}),
        _decision("answer", {"text": "Recreated the year folders here."}),
    ])
    builtins.input = lambda _p="": "y"
    controller.run_turn("redo the folder task from the other window", Config(max_steps=1))
    turn = state.load_recent_turns("me", 5)[-1]
    tool_seq = [s["tool"] for s in turn["steps"]]
    check("loop_read_then_command",
          tool_seq == ["read_session", "run_command"]
          and ran["cmd"] == "mkdir 2020 2021 2022 2023 2024 2025 2026",
          f"seq={tool_seq} cmd={ran['cmd']!r}")


def main() -> int:
    for test in (
        test_read_session_in_schema,
        test_excludes_current_session,
        test_most_recent_first,
        test_recency_filter_drops_stale,
        test_summary_keeps_last_requests_and_cwd,
        test_max_sessions_cap,
        test_empty_when_only_current,
        test_block_empty_when_no_others,
        test_block_lists_id_cwd_requests,
        test_detail_renders_commands_and_answer,
        test_detail_self_is_rejected,
        test_detail_unknown_and_empty,
        test_build_injects_block_only_with_others,
        test_other_sessions_before_own_history_and_request,
        test_handle_read_session_returns_detail_and_records,
        test_loop_read_then_run_command,
    ):
        test()

    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    print(f"\n{passed}/{total} passed")

    out_dir = REPO_ROOT / "logs" / "phase8"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "multitask_results.json").write_text(
        json.dumps({"passed": passed, "total": total, "results": results}, indent=2)
    )
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
