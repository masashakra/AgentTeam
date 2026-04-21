"""
ReviewerAgent — MCP Server on port 8103  [TRUE AGENT]
Exposes one tool: review_code(code, original_task) → JSON verdict

True agent loop: run code with own tests → observe real output → issue verdict.
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

mcp = FastMCP("ReviewerAgent")

SYSTEM = """\
You are a senior Python code reviewer. You do NOT just read code — you RUN it.

You have two tools:
  run_python(code) — executes Python code and returns real stdout/stderr output
  finish(verdict_json) — submits your final JSON verdict

Process:
1. Call run_python() with the provided code PLUS your own standard test cases
2. Call run_python() again with edge case tests (empty inputs, duplicates,
   single elements, different types, large inputs, etc.)
3. Observe the actual output — did it produce correct results?
4. Call finish() with a verdict grounded in what you actually observed

Your finish() verdict_json must be a JSON string with this exact structure:
{
  "verdict": "pass" or "fail",
  "summary": "one sentence based on what you observed when running the code",
  "issues": ["list of issues found — empty if pass"],
  "suggestions": ["optional improvements"]
}

Rules:
- ALWAYS run the code at least once before finishing
- Base your verdict on REAL execution results, not assumptions
- If the code crashes or produces wrong output, verdict must be "fail"
- You MUST call finish() as your final action"""

REVIEWER_TOOLS = [
    {"type": "function", "function": {
        "name": "run_python",
        "description": "Execute Python code and return real stdout + stderr.",
        "parameters": {"type": "object",
            "properties": {"code": {"type": "string", "description": "Python code to execute (implementation + test cases)"}},
            "required": ["code"]},
    }},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Submit the final review verdict. Call only after running the code.",
        "parameters": {"type": "object",
            "properties": {"verdict_json": {"type": "string",
                "description": 'JSON: {"verdict":"pass/fail","summary":"...","issues":[...],"suggestions":[...]}'}},
            "required": ["verdict_json"]},
    }},
]


def _run_python(code: str) -> str:
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout + result.stderr
        return output[:2000] if output else "(no output — code ran silently)"
    except subprocess.TimeoutExpired:
        return "ERROR: Code execution timed out (10s limit)"
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def review_code(code: str, original_task: str) -> str:
    """
    Review Python code by actually running it with test cases, then return a JSON verdict.

    Args:
        code: The Python code to review.
        original_task: The original task the code should solve.

    Returns:
        JSON string: {verdict, summary, issues, suggestions}
    """
    print(f"[ReviewerAgent] Starting review — {len(code)} chars...")

    messages = [{"role": "user", "content": (
        f"Original task: {original_task}\n\n"
        f"Code to review:\n```python\n{code}\n```\n\n"
        "Run this code with standard tests AND edge cases to verify it works correctly, "
        "then call finish() with your verdict."
    )}]
    verdict = ""

    for iteration in range(MAX_ITERATIONS):
        assistant_msg = groq_chat(messages, REVIEWER_TOOLS, SYSTEM, "required", 2000)
        messages.append(assistant_msg)

        tc = get_tool_call(assistant_msg)
        if tc is None:
            break
        name, args, call_id = tc

        if name == "run_python":
            output = _run_python(args["code"])
            print(f"[ReviewerAgent] run_python iter {iteration+1} → {output[:60].strip()}...")
            messages.append(tool_result_message(call_id, output))

        elif name == "finish":
            verdict = args["verdict_json"].strip()
            if verdict.startswith("```"):
                lines = verdict.splitlines()
                inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
                verdict = "\n".join(inner).strip()
            print(f"[ReviewerAgent] Verdict after {iteration+1} iterations: {verdict[:60]}...")
            messages.append(tool_result_message(call_id, "accepted"))
            break

        else:
            messages.append(tool_result_message(call_id, f"Unknown tool: {name}"))

    return verdict


if __name__ == "__main__":
    print("[ReviewerAgent] Starting on port 8103...")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8103)
