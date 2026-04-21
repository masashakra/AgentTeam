"""
CoderAgent — MCP Server on port 8102  [TRUE AGENT]
Exposes one tool: write_and_test_code(plan, feedback?) → working Python code

True agent loop: write → run_python → observe → fix → repeat until correct.
Uses Groq (llama-3.3-70b-versatile) via groq_setup.
"""
from __future__ import annotations

import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastmcp import FastMCP

from groq_setup.infer import groq_chat, get_tool_call, tool_result_message

MAX_ITERATIONS = 8

mcp = FastMCP("CoderAgent")

SYSTEM = """\
You are an expert Python developer. Given a technical plan, write Python code that implements it.
You have two tools:
  run_python(code) — executes your code and returns stdout/stderr
  finish(code)     — submits the final clean implementation

Always test your code with run_python before calling finish.
Fix any errors or wrong output you observe. Iterate until the code is correct.
The code passed to finish should be clean with docstrings and type hints."""

CODER_TOOLS = [
    {"type": "function", "function": {
        "name": "run_python",
        "description": "Execute Python code and return stdout + stderr. Use this to test your implementation.",
        "parameters": {"type": "object",
            "properties": {"code": {"type": "string", "description": "Python code to execute"}},
            "required": ["code"]},
    }},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Submit the final working implementation. Call when the code is correct.",
        "parameters": {"type": "object",
            "properties": {"code": {"type": "string", "description": "The final clean Python implementation"}},
            "required": ["code"]},
    }},
]


def _run_python(code: str) -> str:
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout + result.stderr
        return output[:2000] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "ERROR: Code execution timed out (10s limit)"
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def write_and_test_code(plan: str, feedback: str = "") -> str:
    """
    Write Python code from a technical plan, test it, and return the working implementation.

    Args:
        plan: The step-by-step technical plan to implement.
        feedback: Optional reviewer feedback for retries.

    Returns:
        The final working Python implementation.
    """
    print(f"[CoderAgent] Starting implementation ({len(plan)} char plan)...")

    user_text = f"Technical Plan:\n{plan}"
    if feedback:
        user_text += f"\n\nReviewer feedback to fix:\n{feedback}"

    messages = [{"role": "user", "content": user_text}]
    last_code = ""

    for iteration in range(MAX_ITERATIONS):
        assistant_msg = groq_chat(messages, CODER_TOOLS, SYSTEM, "required", 4000)
        messages.append(assistant_msg)

        tc = get_tool_call(assistant_msg)
        if tc is None:
            break
        name, args, call_id = tc

        if name == "run_python":
            code = args["code"]
            last_code = code
            output = _run_python(code)
            print(f"[CoderAgent] run_python iter {iteration+1} → {output[:60].strip()}...")
            messages.append(tool_result_message(call_id, output))

        elif name == "finish":
            last_code = args["code"]
            print(f"[CoderAgent] Done — {len(last_code)} chars")
            messages.append(tool_result_message(call_id, "accepted"))
            break

        else:
            messages.append(tool_result_message(call_id, f"Unknown tool: {name}"))

    print(f"[CoderAgent] Returning implementation ({len(last_code)} chars)")
    return last_code


if __name__ == "__main__":
    print("[CoderAgent] Starting on port 8102...")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8102)
