"""Offline unit tests for Phase 6 memory (the remember/forget tools).

These exercise the state store (add/load/forget, id generation, malformed
file), context.memory_block (labeled block, ids, empty case, injected only
when non-empty), controller._handle_memory (store / edit / forget-missing /
empty fact), and the run_turn loop end to end with a scripted fake LPU —
no network, no model, no real subprocess. state.MEMORIES_PATH and
state.SESSIONS_DIR are redirected to temp dirs; llm.call and
tools.run_command are stubbed.

Run from the repo root (no litellm needed, but any python3 works):

    /usr/bin/python3 tests/memory_tests.py

Prints a summary and writes logs/phase6/memory_results.json.
"""

import builtins
import json
import os
import sys
import tempfile
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


def _fresh_memories() -> None:
    """Point the memory store at a brand-new empty temp file."""
    state.MEMORIES_PATH = Path(tempfile.mkdtemp()) / "memories.json"


def _fresh_session() -> str:
    state.SESSIONS_DIR = Path(tempfile.mkdtemp())
    os.environ["DOIT_SESSION"] = "memory_test"
    return "memory_test"


def _script_llm(decisions) -> None:
    queue = list(decisions)

    def _call(messages, tool_schemas, config, session_id):
        return queue.pop(0)

    llm.call = _call


def _decision(tool, args):
    return llm.Decision(tool_name=tool, args=args, assistant_message={}, tool_call_id=None)


# --- schema ---------------------------------------------------------------

def test_tools_in_schema():
    names = {s["function"]["name"] for s in tools.TOOL_SCHEMAS}
    remember = next(s for s in tools.TOOL_SCHEMAS if s["function"]["name"] == "remember")
    forget = next(s for s in tools.TOOL_SCHEMAS if s["function"]["name"] == "forget")
    check("tools_in_schema",
          {"remember", "forget"} <= names
          and remember["function"]["parameters"]["required"] == ["fact"]
          and forget["function"]["parameters"]["required"] == ["id"],
          f"names={sorted(names)}")


# --- state store ----------------------------------------------------------

def test_add_and_load():
    _fresh_memories()
    r1 = state.add_memory("my project folder is ~/ass3")
    r2 = state.add_memory("prefer ls by size")
    loaded = state.load_memories()
    check("add_and_load",
          [m["text"] for m in loaded] == ["my project folder is ~/ass3", "prefer ls by size"]
          and r1["id"] == "m1" and r2["id"] == "m2"
          and all("ts" in m for m in loaded),
          f"ids={[m['id'] for m in loaded]}")


def test_ids_increment_past_highest():
    _fresh_memories()
    state.add_memory("a")            # m1
    state.add_memory("b")            # m2
    state.forget_memory("m1")        # remove the lowest; highest is still m2
    r = state.add_memory("c")        # must be m3, not reuse m1
    check("ids_increment", r["id"] == "m3", f"id={r['id']}")


def test_forget_removes_and_reports():
    _fresh_memories()
    state.add_memory("a")            # m1
    state.add_memory("b")            # m2
    removed = state.forget_memory("m1")
    missing = state.forget_memory("m9")
    remaining = [m["id"] for m in state.load_memories()]
    check("forget_removes",
          removed is True and missing is False and remaining == ["m2"],
          f"remaining={remaining}")


def test_missing_and_malformed_file_yield_empty():
    _fresh_memories()  # file does not exist yet
    empty_missing = state.load_memories()
    state.MEMORIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    state.MEMORIES_PATH.write_text("{ not valid json ][")
    empty_malformed = state.load_memories()
    check("missing_malformed_empty",
          empty_missing == [] and empty_malformed == [],
          f"missing={empty_missing} malformed={empty_malformed}")


# --- context.memory_block -------------------------------------------------

def test_memory_block_empty_when_no_memories():
    _fresh_memories()
    check("block_empty", context.memory_block() == "")


def test_memory_block_lists_ids_and_text():
    _fresh_memories()
    state.add_memory("project folder is ~/ass3")
    state.add_memory("prefer ls by size")
    block = context.memory_block()
    check("block_lists",
          "[m1] project folder is ~/ass3" in block
          and "[m2] prefer ls by size" in block
          and "persistent memory" in block.lower(),
          f"block={block!r}")


def test_build_messages_injects_block_only_when_nonempty():
    _fresh_memories()
    session = _fresh_session()
    without = context.build_messages("hi", Config(), session)
    state.add_memory("project folder is ~/ass3")
    with_mem = context.build_messages("hi", Config(), session)
    joined_without = " ".join(m["content"] for m in without)
    joined_with = " ".join(m["content"] for m in with_mem)
    # The system prompt itself mentions "persistent memory", so assert on the
    # actual stored fact + the extra message the block adds, not that phrase.
    check("build_injects_block",
          "project folder is ~/ass3" not in joined_without
          and "[m1] project folder is ~/ass3" in joined_with
          and len(with_mem) == len(without) + 1,
          f"lens={len(without)}->{len(with_mem)}")


# --- controller._handle_memory --------------------------------------------

def test_handle_remember_stores_and_reports():
    _fresh_memories()
    steps = []
    obs = controller._handle_memory("remember", {"fact": "prefer eza"}, steps)
    stored = state.load_memories()
    check("handle_remember",
          len(stored) == 1 and stored[0]["text"] == "prefer eza"
          and steps[-1]["memory_id"] == "m1" and "m1" in obs,
          f"obs={obs!r}")


def test_handle_remember_empty_fact_noop():
    _fresh_memories()
    steps = []
    obs = controller._handle_memory("remember", {"fact": "   "}, steps)
    check("handle_remember_empty",
          state.load_memories() == [] and steps[-1].get("error") == "empty fact"
          and "empty" in obs.lower(),
          f"obs={obs!r}")


def test_handle_forget_missing_reports_false():
    _fresh_memories()
    steps = []
    obs = controller._handle_memory("forget", {"id": "m7"}, steps)
    check("handle_forget_missing",
          steps[-1]["removed"] is False and "no memory" in obs.lower(),
          f"obs={obs!r}")


# --- run_turn integration -------------------------------------------------

def test_loop_remember_then_answer():
    """A single turn stores a fact AND answers — remember is not terminal."""
    _fresh_memories()
    session = _fresh_session()
    _script_llm([
        _decision("remember", {"fact": "my project folder is ~/ass3"}),
        _decision("answer", {"text": "Got it — noted your project folder."}),
    ])
    controller.run_turn("remember that ~/ass3 is my project folder", Config(max_steps=1))
    stored = [m["text"] for m in state.load_memories()]
    turn = state.load_recent_turns(session, 5)[-1]
    tool_seq = [s["tool"] for s in turn["steps"]]
    check("remember_then_answer",
          stored == ["my project folder is ~/ass3"]
          and tool_seq == ["remember"]
          and turn["final_answer"].startswith("Got it"),
          f"seq={tool_seq} stored={stored}")


def test_loop_remember_then_run_command():
    """remember first, then the terminal command, in single-command mode."""
    _fresh_memories()
    session = _fresh_session()
    ran = {"cmd": None}
    tools.run_command = lambda cmd, shell, timeout: ran.__setitem__("cmd", cmd) or \
        tools.CommandResult(stdout="made it\n", stderr="", returncode=0)
    _script_llm([
        _decision("remember", {"fact": "my project folder is ~/proj"}),
        _decision("run_command", {"command": "mkdir ~/proj", "is_destructive": True,
                                  "explanation": "create the folder"}),
    ])
    builtins.input = lambda _p="": "y"  # confirm the destructive command
    controller.run_turn("make ~/proj and remember it's my project", Config(max_steps=1))
    stored = [m["text"] for m in state.load_memories()]
    turn = state.load_recent_turns(session, 5)[-1]
    tool_seq = [s["tool"] for s in turn["steps"]]
    check("remember_then_command",
          stored == ["my project folder is ~/proj"]
          and ran["cmd"] == "mkdir ~/proj"
          and tool_seq == ["remember", "run_command"],
          f"seq={tool_seq} cmd={ran['cmd']!r}")


def test_loop_edit_is_forget_then_remember():
    """Editing a fact: forget the old id, remember the new version, answer."""
    _fresh_memories()
    session = _fresh_session()
    state.add_memory("prefer ls sorted by size")  # m1, pre-existing
    _script_llm([
        _decision("forget", {"id": "m1"}),
        _decision("remember", {"fact": "ask each time which sort order to use"}),
        _decision("answer", {"text": "Updated — I'll ask each time."}),
    ])
    controller.run_turn("I changed my mind about the sort order — ask me each time",
                        Config(max_steps=1))
    stored = [m["text"] for m in state.load_memories()]
    turn = state.load_recent_turns(session, 5)[-1]
    tool_seq = [s["tool"] for s in turn["steps"]]
    check("edit_forget_then_remember",
          stored == ["ask each time which sort order to use"]
          and tool_seq == ["forget", "remember"],
          f"seq={tool_seq} stored={stored}")


def main() -> int:
    for test in (
        test_tools_in_schema,
        test_add_and_load,
        test_ids_increment_past_highest,
        test_forget_removes_and_reports,
        test_missing_and_malformed_file_yield_empty,
        test_memory_block_empty_when_no_memories,
        test_memory_block_lists_ids_and_text,
        test_build_messages_injects_block_only_when_nonempty,
        test_handle_remember_stores_and_reports,
        test_handle_remember_empty_fact_noop,
        test_handle_forget_missing_reports_false,
        test_loop_remember_then_answer,
        test_loop_remember_then_run_command,
        test_loop_edit_is_forget_then_remember,
    ):
        test()

    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    print(f"\n{passed}/{total} passed")

    out_dir = REPO_ROOT / "logs" / "phase6"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "memory_results.json").write_text(
        json.dumps({"passed": passed, "total": total, "results": results}, indent=2)
    )
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
