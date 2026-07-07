"""Offline unit tests for the prompted adapter's JSON handling.

These exercise the extraction/validation/retry logic in doitlib/llm.py
*without* a running Ollama, by feeding it the exact malformed replies
weak models produce (fenced JSON, JSON-in-prose, hallucinated tool
names, dropped args) and by stubbing litellm.completion for the retry
path. They are the defense-in-depth evidence for the model-comparison
chapter: layer-1 (the model) failing, layer-2 (our parser) recovering.

Run with the interpreter that has litellm installed, from the repo root:

    /usr/bin/python3 tests/prompted_adapter_tests.py

Prints a summary and writes a machine-readable result file to
logs/phase3/prompted_adapter_results.json.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from doitlib import llm  # noqa: E402
from doitlib.tools import TOOL_SCHEMAS  # noqa: E402

VALID_NAMES = {schema["function"]["name"] for schema in TOOL_SCHEMAS}

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append({"case": name, "pass": ok, "detail": detail})
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


# --- extraction / validation (no network) --------------------------------

def test_clean_json():
    raw = '{"tool": "run_command", "args": {"command": "ls -la", ' \
          '"is_destructive": false, "explanation": "list files"}}'
    d = llm._parse_prompted_reply(raw, VALID_NAMES)
    check("clean_json", d.tool_name == "run_command"
          and d.args["command"] == "ls -la" and d.tool_call_id is None)


def test_fenced_json():
    raw = 'Sure!\n```json\n{"tool": "answer", "args": {"text": "hi"}}\n```\n'
    d = llm._parse_prompted_reply(raw, VALID_NAMES)
    check("fenced_json", d.tool_name == "answer" and d.args["text"] == "hi")


def test_json_in_prose():
    raw = 'Here is the JSON you asked for: {"tool": "answer", ' \
          '"args": {"text": "done"}} — hope that helps!'
    d = llm._parse_prompted_reply(raw, VALID_NAMES)
    check("json_in_prose", d.tool_name == "answer" and d.args["text"] == "done")


def test_braces_inside_string_value():
    # A brace inside a string must not confuse the balanced-object scanner.
    raw = '{"tool": "run_command", "args": {"command": "echo \\"{}\\"", ' \
          '"is_destructive": false, "explanation": "print braces"}}'
    d = llm._parse_prompted_reply(raw, VALID_NAMES)
    check("braces_inside_string", d.args["command"] == 'echo "{}"')


def test_hallucinated_tool_name_rejected():
    raw = '{"tool": "execute_shell", "args": {"command": "ls"}}'
    try:
        llm._parse_prompted_reply(raw, VALID_NAMES)
        check("hallucinated_tool_rejected", False, "should have raised")
    except ValueError as error:
        check("hallucinated_tool_rejected", "execute_shell" in str(error), str(error))


def test_non_object_args_rejected():
    raw = '{"tool": "answer", "args": "just a string"}'
    try:
        llm._parse_prompted_reply(raw, VALID_NAMES)
        check("non_object_args_rejected", False, "should have raised")
    except ValueError as error:
        check("non_object_args_rejected", "args" in str(error), str(error))


def test_total_garbage_rejected():
    try:
        llm._parse_prompted_reply("I cannot do that.", VALID_NAMES)
        check("garbage_rejected", False, "should have raised")
    except ValueError as error:
        check("garbage_rejected", "no JSON object" in str(error), str(error))


# --- the retry path (stubbed litellm) ------------------------------------

class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]

    def model_dump(self):
        return {"stub": True, "content": self.choices[0].message.content}


def _run_prompted_with_replies(replies):
    """Drive _call_prompted with a scripted sequence of raw model replies."""
    from doitlib.config import Config

    calls = {"n": 0, "messages": []}

    def fake_completion(model, messages, temperature):
        calls["messages"].append(messages)
        content = replies[calls["n"]]
        calls["n"] += 1
        return _FakeResponse(content)

    original_completion = llm.litellm.completion
    original_log = llm.state.log_llm_call
    llm.litellm.completion = fake_completion
    llm.state.log_llm_call = lambda *a, **k: None
    try:
        messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "list files"},
        ]
        config = Config(model="ollama/llama3:8b", adapter="prompted")
        decision = llm._call_prompted(messages, TOOL_SCHEMAS, config, "test")
        return decision, calls
    finally:
        llm.litellm.completion = original_completion
        llm.state.log_llm_call = original_log


def test_retry_recovers():
    # First reply is garbage; second is valid -> Decision returned, 2 calls,
    # and the retry conversation carried the error feedback.
    bad = "I think you want: ls -la"
    good = '{"tool": "run_command", "args": {"command": "ls -la", ' \
           '"is_destructive": false, "explanation": "list"}}'
    decision, calls = _run_prompted_with_replies([bad, good])
    retry_had_feedback = any(
        "not a usable JSON tool call" in m.get("content", "")
        for m in calls["messages"][1]
    )
    check("retry_recovers", decision.tool_name == "run_command"
          and calls["n"] == 2 and retry_had_feedback,
          f"calls={calls['n']} feedback={retry_had_feedback}")


def test_two_failures_raise():
    try:
        _run_prompted_with_replies(["nope", "still nope"])
        check("two_failures_raise", False, "should have raised RuntimeError")
    except RuntimeError as error:
        check("two_failures_raise", "did not return a usable" in str(error), str(error))


def test_tool_text_injected_into_system():
    injected = llm._inject_tool_instructions(
        [{"role": "system", "content": "BASE"}], TOOL_SCHEMAS
    )
    content = injected[0]["content"]
    check("tools_in_system_prompt",
          "BASE" in content and "run_command" in content and "ONLY" in content.upper())


def main() -> int:
    for test in (
        test_clean_json, test_fenced_json, test_json_in_prose,
        test_braces_inside_string_value, test_hallucinated_tool_name_rejected,
        test_non_object_args_rejected, test_total_garbage_rejected,
        test_retry_recovers, test_two_failures_raise,
        test_tool_text_injected_into_system,
    ):
        test()

    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    print(f"\n{passed}/{total} passed")

    out_dir = REPO_ROOT / "logs" / "phase3"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "prompted_adapter_results.json").write_text(
        json.dumps({"passed": passed, "total": total, "results": results}, indent=2)
    )
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
