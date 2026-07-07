"""Offline unit tests for Phase 4 multi-turn history replay.

These exercise context.history_messages / _replay_turn / build_messages and
the D7 tiered-truncation budget in tools.truncate_for_context, without any
network or model. A temporary session JSONL stands in for a real session's
history (state.SESSIONS_DIR is redirected to a temp dir), so the tests
prove that past turns come back as proper U:/A: chat messages, that older
output uses the cold budget, and that only the last K turns survive.

Run from the repo root (no litellm needed, but any python3 works):

    /usr/bin/python3 tests/history_tests.py

Prints a summary and writes logs/phase4/history_results.json.
"""

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from doitlib import context, state, tools  # noqa: E402
from doitlib.config import Config  # noqa: E402

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append({"case": name, "pass": bool(ok), "detail": detail})
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def _seed_session(turn_records: list) -> str:
    """Write turn records to a fresh temp session file, return its id."""
    tmp = Path(tempfile.mkdtemp())
    state.SESSIONS_DIR = tmp
    session_id = "hist_test"
    for record in turn_records:
        state.record_turn(session_id, record)
    return session_id


def _run_cmd_turn(request, command, stdout, rc=0, stderr=""):
    return {
        "ts": 0, "cwd": "/tmp", "request": request,
        "steps": [{
            "tool": "run_command",
            "args": {"command": command, "is_destructive": False, "explanation": "x"},
            "stdout": stdout, "stderr": stderr, "rc": rc,
        }],
        "final_answer": None,
    }


def _answer_turn(request, answer):
    return {"ts": 0, "cwd": "/tmp", "request": request, "steps": [], "final_answer": answer}


def _blocked_turn(request, command, reason, answer):
    return {
        "ts": 0, "cwd": "/tmp", "request": request,
        "steps": [{
            "tool": "run_command",
            "args": {"command": command, "is_destructive": True, "explanation": "x"},
            "blocked_reason": reason, "stdout": "", "stderr": "", "rc": None,
        }],
        "final_answer": answer,
    }


# --- truncation budgets (D7) ---------------------------------------------

def test_hot_budget_default():
    text = "A" * 10000
    out = tools.truncate_for_context(text)  # defaults = hot 3000/1000
    check("hot_budget_default",
          out.startswith("A" * 3000) and out.rstrip().endswith("A" * 1000)
          and "truncated" in out, f"len={len(out)}")


def test_cold_budget_smaller_than_hot():
    text = "B" * 10000
    hot = tools.truncate_for_context(text, tools.HOT_HEAD_CHARS, tools.HOT_TAIL_CHARS)
    cold = tools.truncate_for_context(text, tools.COLD_HEAD_CHARS, tools.COLD_TAIL_CHARS)
    check("cold_smaller_than_hot", len(cold) < len(hot), f"cold={len(cold)} hot={len(hot)}")


def test_short_output_untouched():
    text = "just a few lines\n"
    check("short_untouched", tools.truncate_for_context(text) == text)


# --- replay of a single turn ---------------------------------------------

def test_run_command_turn_replays_as_chat():
    sid = _seed_session([_run_cmd_turn("list files", "ls ~/Documents",
                                       "report.pdf notes.txt", rc=0)])
    msgs = context.history_messages(sid)
    roles = [m["role"] for m in msgs]
    check("run_command_replay",
          roles == ["user", "assistant", "user"]
          and msgs[0]["content"] == "list files"
          and "ls ~/Documents" in msgs[1]["content"]
          and "report.pdf" in msgs[2]["content"],
          f"roles={roles}")


def test_answer_turn_replays():
    sid = _seed_session([_answer_turn("how do I list files?", "Use ls -la.")])
    msgs = context.history_messages(sid)
    check("answer_replay",
          [m["role"] for m in msgs] == ["user", "assistant"]
          and msgs[1]["content"] == "Use ls -la.")


def test_blocked_turn_shows_not_run():
    sid = _seed_session([_blocked_turn("delete everything", "rm -rf /",
                                       "declined_by_user", "Aborted.")])
    msgs = context.history_messages(sid)
    joined = " ".join(m["content"] for m in msgs)
    check("blocked_replay",
          "did not run" in joined and "rm -rf /" in joined and "Aborted." in joined)


def test_history_output_uses_cold_budget():
    big = "L" * 8000
    sid = _seed_session([_run_cmd_turn("find things", "find /", big, rc=0)])
    msgs = context.history_messages(sid)
    output_msg = msgs[2]["content"]
    # cold budget (1000+300) must trim an 8k output well below the hot 4k budget
    check("history_uses_cold_budget",
          "truncated" in output_msg and len(output_msg) < 2000,
          f"len={len(output_msg)}")


# --- K limit and ordering ------------------------------------------------

def test_only_last_k_turns_kept():
    turns = [_answer_turn(f"q{i}", f"a{i}") for i in range(context.HISTORY_TURNS + 5)]
    sid = _seed_session(turns)
    msgs = context.history_messages(sid)
    requests = [m["content"] for m in msgs if m["role"] == "user"]
    check("only_last_k",
          len(requests) == context.HISTORY_TURNS
          and requests[0] == "q5" and requests[-1] == f"q{context.HISTORY_TURNS + 4}",
          f"kept={len(requests)} first={requests[0]}")


def test_no_history_file_is_empty():
    state.SESSIONS_DIR = Path(tempfile.mkdtemp())
    check("no_history_empty", context.history_messages("never_seen") == [])


# --- full assembly --------------------------------------------------------

def test_build_messages_places_history_between_env_and_request():
    sid = _seed_session([_run_cmd_turn("list files", "ls", "a.txt", rc=0)])
    msgs = context.build_messages("now sort them by date", Config(), sid)
    check("build_messages_order",
          msgs[0]["role"] == "system"
          and "Environment:" in msgs[1]["content"]
          and msgs[-1]["content"] == "now sort them by date"
          and any("ls" in m["content"] for m in msgs[2:-1]),
          f"n={len(msgs)}")


def main() -> int:
    for test in (
        test_hot_budget_default, test_cold_budget_smaller_than_hot,
        test_short_output_untouched, test_run_command_turn_replays_as_chat,
        test_answer_turn_replays, test_blocked_turn_shows_not_run,
        test_history_output_uses_cold_budget, test_only_last_k_turns_kept,
        test_no_history_file_is_empty,
        test_build_messages_places_history_between_env_and_request,
    ):
        test()

    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    print(f"\n{passed}/{total} passed")

    out_dir = REPO_ROOT / "logs" / "phase4"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "history_results.json").write_text(
        json.dumps({"passed": passed, "total": total, "results": results}, indent=2)
    )
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
