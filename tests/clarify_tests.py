"""Offline unit tests for Phase 5 clarifications (the ask_user tool).

These exercise the schema, controller._prompt_user (numbered-option
resolution + empty/EOF handling), controller._handle_ask_user (normal
reply / no-answer default / non-annoyance cap / Ctrl-C abort), and the
run_turn loop end to end with a scripted fake LPU — no network, no model,
no real subprocess. state.SESSIONS_DIR and builtins.input are redirected;
llm.call and tools.run_command are stubbed.

Run from the repo root (no litellm needed, but any python3 works):

    /usr/bin/python3 tests/clarify_tests.py

Prints a summary and writes logs/phase5/clarify_results.json.
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


def _fake_input(replies):
    """Return an input() stand-in that yields the given replies in order."""
    queue = list(replies)

    def _input(_prompt=""):
        if not queue:
            raise EOFError
        value = queue.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    return _input


# --- schema ---------------------------------------------------------------

def test_ask_user_in_schema():
    names = {s["function"]["name"] for s in tools.TOOL_SCHEMAS}
    ask = next(s for s in tools.TOOL_SCHEMAS if s["function"]["name"] == "ask_user")
    required = ask["function"]["parameters"]["required"]
    props = ask["function"]["parameters"]["properties"]
    check("ask_user_in_schema",
          "ask_user" in names and required == ["question"] and "options" in props,
          f"required={required}")


# --- _prompt_user ---------------------------------------------------------

def test_prompt_numbered_option_maps_to_text():
    builtins.input = _fake_input(["2"])
    reply = controller._prompt_user("which one?", ["alpha", "beta", "gamma"])
    check("numbered_option_maps", reply == "beta", f"reply={reply!r}")


def test_prompt_out_of_range_number_kept_verbatim():
    builtins.input = _fake_input(["9"])
    reply = controller._prompt_user("which one?", ["alpha", "beta"])
    check("out_of_range_verbatim", reply == "9", f"reply={reply!r}")


def test_prompt_free_text_returned():
    builtins.input = _fake_input(["by size"])
    reply = controller._prompt_user("how?", ["by date"])
    check("free_text_returned", reply == "by size", f"reply={reply!r}")


def test_prompt_eof_is_empty():
    builtins.input = _fake_input([EOFError()])
    reply = controller._prompt_user("how?", [])
    check("eof_is_empty", reply == "")


# --- _handle_ask_user -----------------------------------------------------

def test_handle_reply_feeds_answer_back():
    builtins.input = _fake_input(["yes, the src folder"])
    steps = []
    observation, aborted = controller._handle_ask_user({"question": "which folder?"}, 0, steps)
    check("reply_feeds_back",
          aborted is None and "yes, the src folder" in observation
          and steps[-1]["reply"] == "yes, the src folder",
          f"obs={observation!r}")


def test_handle_empty_reply_uses_default():
    builtins.input = _fake_input([""])
    steps = []
    observation, aborted = controller._handle_ask_user({"question": "which?"}, 0, steps)
    check("empty_uses_default",
          aborted is None and "no answer" in observation.lower()
          and "default" in observation.lower() and steps[-1]["reply"] == "",
          f"obs={observation!r}")


def test_handle_cap_stops_asking():
    prompted = {"n": 0}
    original = controller._prompt_user
    controller._prompt_user = lambda *a, **k: prompted.__setitem__("n", prompted["n"] + 1) or "x"
    try:
        steps = []
        observation, aborted = controller._handle_ask_user(
            {"question": "again?"}, controller.MAX_CLARIFICATIONS, steps
        )
    finally:
        controller._prompt_user = original
    check("cap_stops_asking",
          aborted is None and prompted["n"] == 0
          and steps[-1].get("clarification_capped") is True
          and "limit" in observation.lower(),
          f"prompted={prompted['n']}")


def test_handle_ctrl_c_aborts():
    builtins.input = _fake_input([KeyboardInterrupt()])
    steps = []
    observation, aborted = controller._handle_ask_user({"question": "which?"}, 0, steps)
    check("ctrl_c_aborts",
          aborted is not None and "abort" in aborted.lower()
          and steps[-1].get("aborted") is True,
          f"aborted={aborted!r}")


# --- run_turn loop integration -------------------------------------------

def _script_llm(decisions):
    """Redirect llm.call to hand back a scripted list of Decisions."""
    queue = list(decisions)

    def _call(messages, tool_schemas, config, session_id):
        return queue.pop(0)

    llm.call = _call


def _decision(tool, args):
    return llm.Decision(tool_name=tool, args=args, assistant_message={}, tool_call_id=None)


def _fresh_session():
    state.SESSIONS_DIR = Path(tempfile.mkdtemp())
    os.environ["DOIT_SESSION"] = "clarify_test"  # run_turn reads this via get_session_id
    return "clarify_test"


def test_loop_ask_then_run_command():
    """ask_user does not consume the single command step; command still runs."""
    session = _fresh_session()
    ran = {"cmd": None}
    tools.run_command = lambda cmd, shell, timeout: ran.__setitem__("cmd", cmd) or \
        tools.CommandResult(stdout="done\n", stderr="", returncode=0)
    _script_llm([
        _decision("ask_user", {"question": "which folder — src or build?",
                               "options": ["src", "build"]}),
        _decision("run_command", {"command": "ls src", "is_destructive": False,
                                  "explanation": "list src"}),
    ])
    builtins.input = _fake_input(["1"])  # picks "src"
    controller.run_turn("clean the folder", Config(max_steps=1))

    turn = state.load_recent_turns(session, 5)[-1]
    tool_seq = [s["tool"] for s in turn["steps"]]
    check("ask_then_run",
          ran["cmd"] == "ls src" and tool_seq == ["ask_user", "run_command"]
          and turn["steps"][0]["reply"] == "src",
          f"seq={tool_seq} cmd={ran['cmd']!r}")


def test_loop_cap_limits_prompts():
    """A model that keeps asking is prompted at most MAX_CLARIFICATIONS times."""
    _fresh_session()
    prompts = {"n": 0}

    def _counting_input(_prompt=""):
        prompts["n"] += 1
        return "whatever"

    builtins.input = _counting_input
    # ask forever; the loop guard + cap must still terminate the turn
    _script_llm([_decision("ask_user", {"question": "q?"}) for _ in range(10)])
    controller.run_turn("ambiguous thing", Config(max_steps=1))
    check("cap_limits_prompts",
          prompts["n"] == controller.MAX_CLARIFICATIONS,
          f"prompted={prompts['n']} (cap={controller.MAX_CLARIFICATIONS})")


def test_loop_ctrl_c_ends_turn():
    session = _fresh_session()
    _script_llm([_decision("ask_user", {"question": "which?"})])
    builtins.input = _fake_input([KeyboardInterrupt()])
    controller.run_turn("do the thing", Config(max_steps=1))
    turn = state.load_recent_turns(session, 5)[-1]
    check("ctrl_c_ends_turn",
          "abort" in (turn["final_answer"] or "").lower()
          and turn["steps"][-1].get("aborted") is True,
          f"final={turn['final_answer']!r}")


def main() -> int:
    for test in (
        test_ask_user_in_schema,
        test_prompt_numbered_option_maps_to_text,
        test_prompt_out_of_range_number_kept_verbatim,
        test_prompt_free_text_returned,
        test_prompt_eof_is_empty,
        test_handle_reply_feeds_answer_back,
        test_handle_empty_reply_uses_default,
        test_handle_cap_stops_asking,
        test_handle_ctrl_c_aborts,
        test_loop_ask_then_run_command,
        test_loop_cap_limits_prompts,
        test_loop_ctrl_c_ends_turn,
    ):
        test()

    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    print(f"\n{passed}/{total} passed")

    out_dir = REPO_ROOT / "logs" / "phase5"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "clarify_results.json").write_text(
        json.dumps({"passed": passed, "total": total, "results": results}, indent=2)
    )
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
