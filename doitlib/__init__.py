"""doitlib — the implementation behind the `doit` entry point.

Architecture (see PLAN.md): a Python Controller wrapping an LPU (the
LLM). The LLM only ever sees text and returns a structured Decision;
the controller owns the loop, state, tool execution, and safety.
"""
