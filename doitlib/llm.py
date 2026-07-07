"""The single gateway to the LPU (the LLM).

call() sends the message list plus the tool schemas through LiteLLM and
returns a Decision — the structured instruction the controller acts on.
The LLM never executes anything itself.

Phase 1 ships the *native* adapter only (models with built-in tool
calling, e.g. openai/gpt-4o-mini). The *prompted* adapter for models
without tool calling arrives in Phase 3.
"""

import json
from dataclasses import dataclass, field
from typing import Optional

import litellm

from . import state
from .config import Config


@dataclass
class Decision:
    """One structured instruction from the LPU: a tool to run, with args.

    assistant_message and tool_call_id carry the provider-format message
    that produced this decision, so the controller can append it (plus a
    matching tool-result message) to the conversation for the next step.
    """

    tool_name: str
    args: dict
    assistant_message: dict = field(default_factory=dict)
    tool_call_id: Optional[str] = None


def call(messages: list, tool_schemas: list, config: Config, session_id: str) -> Decision:
    """Ask the model for its next decision (native tool-calling adapter).

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
        assistant_message=message.model_dump(),
        tool_call_id=tool_call.id,
    )
