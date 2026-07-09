"""The single gateway to the LPU (the LLM).

call() sends the message list plus the tool schemas to the model and
returns a Decision — the structured instruction the controller acts on.
The LLM never executes anything itself.

Two adapters live behind the one call() interface (Phase 3, "model
flexibility"). The controller never knows which one ran:

- native adapter  (_call_native): models with built-in tool calling
  (openai/gpt-4o-mini, ollama/mistral:7b). LiteLLM's tools= parameter;
  the model emits a structured tool_calls object we parse directly.
- prompted adapter (_call_prompted): models without tool calling
  (ollama/llama3:8b). The tool schemas and a "reply with ONLY JSON"
  instruction go into the system prompt; we defensively extract and
  validate the JSON ourselves, retrying once with the parse error fed
  back. This is where weak models misbehave (prose around the JSON,
  hallucinated tool names, dropped args) — recovery here is the core of
  the model-comparison report.

config.adapter picks the adapter ("native" | "prompted").
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import litellm

from . import state
from .config import Config

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# The prompted adapter gets one retry when parsing fails; a second failure
# is surfaced to the user (and fully logged) rather than silently guessed.
_PROMPTED_MAX_ATTEMPTS = 2


@dataclass
class Decision:
    """One structured instruction from the LPU: a tool to run, with args.

    assistant_message and tool_call_id carry the provider-format message
    that produced this decision, so the controller can append it (plus a
    matching tool-result message) to the conversation for the next step.

    - native adapter: assistant_message is the raw tool-call message and
      tool_call_id is set, so results feed back via the tool role.
    - prompted adapter: assistant_message is the plain-text JSON reply and
      tool_call_id is None, so results feed back as a plain user message.
    """

    tool_name: str
    args: dict
    assistant_message: dict = field(default_factory=dict)
    tool_call_id: Optional[str] = None


def call(messages: list, tool_schemas: list, config: Config, session_id: str) -> Decision:
    """Ask the model for its next decision, via the configured adapter."""
    if config.adapter == "prompted":
        return _call_prompted(messages, tool_schemas, config, session_id)
    return _call_native(messages, tool_schemas, config, session_id)


# --------------------------------------------------------------------------
# Native adapter — LiteLLM tool calling
# --------------------------------------------------------------------------


def _call_native(messages: list, tool_schemas: list, config: Config, session_id: str) -> Decision:
    """Next decision from a model with built-in tool calling.

    Every raw request/response pair is logged to ~/.doit/logs/ as report
    evidence.
    """
    response = litellm.completion(
        model=config.model,
        messages=messages,
        tools=tool_schemas,
        tool_choice="required",  # every reply must be a tool call
        temperature=config.temperature,
    )
    state.log_llm_call(
        session_id,
        request={"model": config.model, "messages": messages, "tools": tool_schemas},
        response=response.model_dump(),
    )

    message = response.choices[0].message
    if not message.tool_calls:
        # Defensive fallback: a plain-text reply is treated as an answer.
        return Decision(tool_name="answer", args={"text": message.content or ""})

    tool_call = message.tool_calls[0]
    try:
        args = json.loads(tool_call.function.arguments)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"model returned unparseable tool arguments: {error}"
        ) from error
    return Decision(
        tool_name=tool_call.function.name,
        args=args,
        assistant_message=_dump_single_tool_call(message, tool_call.id),
        tool_call_id=tool_call.id,
    )


def _dump_single_tool_call(message, tool_call_id: str) -> dict:
    """Drop sibling tool_calls; keep only the one we answer (DECISIONS P6e).

    A native model can return >1 tool_calls in one message. We act on and
    answer only one per loop iteration, so replaying the rest unanswered
    would crash the next call. The dropped one isn't lost — the model
    reissues it once it sees the updated state.
    """
    dumped = message.model_dump()
    if len(dumped.get("tool_calls") or []) > 1:
        dumped["tool_calls"] = [
            call for call in dumped["tool_calls"] if call.get("id") == tool_call_id
        ]
    return dumped


# --------------------------------------------------------------------------
# Prompted adapter — JSON tool protocol hand-rolled in the prompt
# --------------------------------------------------------------------------


def _call_prompted(messages: list, tool_schemas: list, config: Config, session_id: str) -> Decision:
    """Next decision from a model without tool calling.

    The tool schemas are rendered as text into the system prompt and the
    model is asked for a bare JSON object. We extract and validate it
    ourselves; on a parse failure we retry once, appending the failed
    reply and the error so the model can correct itself. A second failure
    raises (the caller shows a clean message; the full exchange is logged).
    """
    valid_names = {schema["function"]["name"] for schema in tool_schemas}
    conversation = _inject_tool_instructions(messages, tool_schemas)
    last_error = ""

    for _ in range(_PROMPTED_MAX_ATTEMPTS):
        response = litellm.completion(
            model=config.model,
            messages=conversation,
            temperature=config.temperature,
        )
        state.log_llm_call(
            session_id,
            request={"model": config.model, "messages": conversation, "adapter": "prompted"},
            response=response.model_dump(),
        )
        raw = response.choices[0].message.content or ""
        try:
            return _parse_prompted_reply(raw, valid_names)
        except ValueError as error:
            last_error = str(error)
            conversation = conversation + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": _retry_prompt(last_error)},
            ]

    raise RuntimeError(
        f"prompted model did not return a usable JSON tool call after "
        f"{_PROMPTED_MAX_ATTEMPTS} attempts: {last_error}"
    )


def _inject_tool_instructions(messages: list, tool_schemas: list) -> list:
    """Return a copy of messages with the JSON tool protocol in the system prompt.

    The native adapter passes tool schemas out-of-band via tools=; here
    there is no such channel, so the schemas (as text) plus the
    "reply with ONLY JSON" envelope are appended to the system message.
    """
    suffix = _suffix_prompt(_render_tools_as_text(tool_schemas))
    out = [dict(message) for message in messages]
    for message in out:
        if message.get("role") == "system":
            message["content"] = message["content"].rstrip() + "\n\n" + suffix
            return out
    out.insert(0, {"role": "system", "content": suffix})
    return out


def _render_tools_as_text(tool_schemas: list) -> str:
    """Render the tool schemas as human/model-readable text for the prompt."""
    blocks = []
    for schema in tool_schemas:
        function = schema["function"]
        parameters = function.get("parameters", {})
        properties = parameters.get("properties", {})
        required = set(parameters.get("required", []))
        if properties:
            arg_lines = [
                f"      - {name} ({spec.get('type', 'string')}, "
                f"{'required' if name in required else 'optional'}): "
                f"{spec.get('description', '').strip()}"
                for name, spec in properties.items()
            ]
            args_text = "\n".join(arg_lines)
        else:
            args_text = "      (no arguments)"
        blocks.append(
            f"  \"{function['name']}\": {function['description']}\n"
            f"    args:\n{args_text}"
        )
    return "\n".join(blocks)


def _parse_prompted_reply(raw: str, valid_names: set) -> Decision:
    """Turn a prompted model's raw text reply into a validated Decision.

    Raises ValueError on anything unusable (no JSON, unknown tool name,
    non-object args) so the caller can retry with the error fed back.
    """
    data = _extract_json_object(raw)
    tool_name = data.get("tool")
    if tool_name not in valid_names:
        raise ValueError(
            f"missing or unknown tool name {tool_name!r}; "
            f"expected one of {sorted(valid_names)}"
        )
    args = data.get("args", {})
    if not isinstance(args, dict):
        raise ValueError(f"'args' must be a JSON object, got {type(args).__name__}")
    return Decision(
        tool_name=tool_name,
        args=args,
        assistant_message={"role": "assistant", "content": raw},
        tool_call_id=None,  # signals the prompted feedback path to the controller
    )


def _extract_json_object(text: str) -> dict:
    """Best-effort extraction of a single JSON object from a model reply.

    Handles the common weak-model failure modes: markdown code fences and
    prose wrapped around the JSON ("Sure! Here's the JSON: {...}"). Tries
    the whole (de-fenced) reply first, then the first balanced {...} run.
    Raises ValueError if nothing parses to a JSON object.
    """
    candidates = []
    stripped = _strip_code_fences(text).strip()
    if stripped:
        candidates.append(stripped)
    balanced = _first_balanced_object(stripped)
    if balanced and balanced != stripped:
        candidates.append(balanced)

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise ValueError("no JSON object found in reply")


def _strip_code_fences(text: str) -> str:
    """Return the contents of the first ``` fenced block, or text unchanged."""
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else text


def _first_balanced_object(text: str) -> Optional[str]:
    """Return the first balanced {...} substring, ignoring braces in strings."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _suffix_prompt(tools_text: str) -> str:
    """The prompted-adapter system-prompt envelope, with tools filled in."""
    template = (PROMPTS_DIR / "prompted_suffix.txt").read_text()
    return template.replace("{tools}", tools_text)


def _retry_prompt(error: str) -> str:
    """The correction message sent after an unparseable prompted reply."""
    template = (PROMPTS_DIR / "prompted_retry.txt").read_text()
    return template.replace("{error}", error)
