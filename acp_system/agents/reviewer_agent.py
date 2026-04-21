"""
ReviewerAgent — ACP Server on port 9003  [TRUE AGENT]

Receives: ACP Run with text message (code) + JSON message (original_task)
Returns:  ACP Run with JSON message (verdict)

True agent loop:
  1. Groq reads the code
  2. Calls run_python() with the code + its OWN test cases → sees REAL output
  3. Calls run_python() again with edge case tests it writes itself
  4. Calls finish() with a verdict grounded in real execution evidence
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from groq_setup.infer import groq_chat, get_tool_call, tool_result_message

from shared.base_agent import BaseACPAgent
from shared.models import (
    AgentCapabilities, AgentManifest, Message,
    extract_json, extract_text, json_message,
)

PORT           = 9003
MAX_ITERATIONS = 8

MANIFEST = AgentManifest(
    name="ReviewerAgent",
    description="True agent: runs code with its own test cases, observes real output, then issues verdict.",
    version="2.0.0",
    capabilities=AgentCapabilities(streaming=True),
    output_modes=["application/json"],
)

SYSTEM = """\
You are a senior Python code reviewer. You do NOT just read code — you RUN it.

You have two tools:
  run_python(code) — executes Python code and returns real stdout/stderr
  finish(verdict)  — submits your final structured verdict

Process:
1. Call run_python() with the code + standard test cases you write
2. Call run_python() again with edge cases (empty inputs, duplicates, single elements, negatives)
3. Observe the actual output — does it match expected results?
4. Call finish() with a verdict based on what you actually observed

The verdict argument must be a JSON object with this structure:
{
  "verdict": "pass" or "fail",
  "summary": "one sentence based on observed execution results",
  "issues": ["critical issues — empty if pass"],
  "suggestions": ["optional improvements"]
}

Rules:
- ALWAYS run the code at least once before finishing
- Base verdict on REAL execution results, not assumptions
- If code crashes or produces wrong output → verdict must be "fail"
- You MUST call finish() as your final action"""

REVIEWER_TOOLS = [
    {"type": "function", "function": {
        "name": "run_python",
        "description": "Execute Python code and return real stdout + stderr. Write implementation + your own test cases.",
        "parameters": {"type": "object",
            "properties": {"code": {"type": "string", "description": "Python code to execute (implementation + test cases)"}},
            "required": ["code"]},
    }},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Submit the final verdict. Only call after running the code.",
        "parameters": {"type": "object",
            "properties": {"verdict": {"type": "string",
                "description": 'JSON string: {"verdict":"pass/fail","summary":"...","issues":[...],"suggestions":[...]}'}},
            "required": ["verdict"]},
    }},
]


def _run_python(code: str) -> str:
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout + result.stderr
        return output[:2000] if output else "(no output — ran silently)"
    except subprocess.TimeoutExpired:
        return "ERROR: Timed out (10s)"
    except Exception as e:
        return f"ERROR: {e}"


class ReviewerAgent(BaseACPAgent):
    def __init__(self):
        super().__init__(MANIFEST)

    async def handle(self, messages: list[Message], run_id: str) -> list[Message]:
        code          = extract_text(messages)
        task_data     = extract_json(messages, name="original_task")
        original_task = task_data.get("task", "")

        print(f"[ReviewerAgent] Starting agent loop — {len(code)} chars of code...")

        chat_messages = [{"role": "user", "content": (
            f"Original task: {original_task}\n\n"
            f"Code to review:\n```python\n{code}\n```\n\n"
            "Run this code with standard AND edge case tests, then call finish() with your verdict."
        )}]
        verdict_data = {}

        for iteration in range(MAX_ITERATIONS):
            assistant_msg = groq_chat(chat_messages, REVIEWER_TOOLS, SYSTEM, "required", 2000)
            chat_messages.append(assistant_msg)

            tc = get_tool_call(assistant_msg)
            if tc is None:
                break
            name, args, call_id = tc

            if name == "run_python":
                output = _run_python(args["code"])
                print(f"[ReviewerAgent] run_python iter {iteration+1} → {output[:60].strip()}...")
                chat_messages.append(tool_result_message(call_id, output))

            elif name == "finish":
                raw = args["verdict"].strip()
                if raw.startswith("```"):
                    lines = raw.splitlines()
                    inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
                    raw   = "\n".join(inner).strip()
                try:
                    verdict_data = json.loads(raw)
                except Exception:
                    verdict_data = {"verdict": "fail", "summary": raw, "issues": [], "suggestions": []}
                print(f"[ReviewerAgent] Verdict after {iteration+1} iterations: {verdict_data.get('verdict','?').upper()}")
                chat_messages.append(tool_result_message(call_id, "accepted"))
                break

            else:
                chat_messages.append(tool_result_message(call_id, f"Unknown tool: {name}"))

        return [json_message(verdict_data, name="review")]


agent = ReviewerAgent()
app   = agent.app

if __name__ == "__main__":
    print(f"[ReviewerAgent] Starting on port {PORT}...")
    agent.serve(PORT)
