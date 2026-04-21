"""
CoderAgent — ACP Server on port 9002  [TRUE AGENT]

Receives: ACP Run with text message (plan) + optional JSON message (feedback)
Returns:  ACP Run with text message (working Python code)

True agent loop:
  1. Groq reads the plan and writes code
  2. Calls run_python() → gets REAL stdout/stderr
  3. Observes output, fixes bugs if needed
  4. Calls finish() only when code is correct
"""
from __future__ import annotations

import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from groq_setup.infer import groq_chat, get_tool_call, tool_result_message

from shared.base_agent import BaseACPAgent
from shared.models import (
    AgentCapabilities, AgentManifest, Message,
    extract_json, extract_text, text_message,
)

PORT           = 9002
MAX_ITERATIONS = 10

MANIFEST = AgentManifest(
    name="CoderAgent",
    description="True agent: writes Python code, executes it, observes output, self-corrects until correct.",
    version="2.0.0",
    capabilities=AgentCapabilities(streaming=True),
)

SYSTEM = """\
You are an expert Python developer. Given a technical plan, implement it in Python.

You have two tools:
  run_python(code) — executes your code and returns real stdout/stderr
  finish(code)     — submits the final clean implementation

Rules:
- Always test with run_python before calling finish
- Fix any errors or wrong output you observe — iterate until correct
- Final code must have docstrings and type hints
- You MUST call finish() as your final action"""

CODER_TOOLS = [
    {"type": "function", "function": {
        "name": "run_python",
        "description": "Execute Python code and return real stdout + stderr. Use to test your implementation.",
        "parameters": {"type": "object",
            "properties": {"code": {"type": "string", "description": "Python code to execute"}},
            "required": ["code"]},
    }},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Submit the final working implementation. Call only after verifying correctness.",
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
        return "ERROR: Timed out (10s)"
    except Exception as e:
        return f"ERROR: {e}"


class CoderAgent(BaseACPAgent):
    def __init__(self):
        super().__init__(MANIFEST)

    async def handle(self, messages: list[Message], run_id: str) -> list[Message]:
        plan     = extract_text(messages)
        feedback = extract_json(messages, name="feedback")

        user_text = f"Technical Plan:\n{plan}"
        if feedback:
            issues      = feedback.get("issues", [])
            suggestions = feedback.get("suggestions", [])
            user_text  += "\n\nReviewer feedback to fix:"
            if issues:
                user_text += f"\nIssues: {issues}"
            if suggestions:
                user_text += f"\nSuggestions: {suggestions}"

        print(f"[CoderAgent] Starting agent loop ({len(plan)} char plan)...")

        chat_messages = [{"role": "user", "content": user_text}]
        last_code = ""

        for iteration in range(MAX_ITERATIONS):
            assistant_msg = groq_chat(chat_messages, CODER_TOOLS, SYSTEM, "required", 4000)
            chat_messages.append(assistant_msg)

            tc = get_tool_call(assistant_msg)
            if tc is None:
                break
            name, args, call_id = tc

            if name == "run_python":
                last_code   = args["code"]
                tool_result = _run_python(last_code)
                print(f"[CoderAgent] run_python iter {iteration+1} → {tool_result[:60].strip()}...")
                chat_messages.append(tool_result_message(call_id, tool_result))

            elif name == "finish":
                last_code = args["code"]
                print(f"[CoderAgent] Done — {len(last_code)} chars after {iteration+1} iterations")
                chat_messages.append(tool_result_message(call_id, "accepted"))
                break

            else:
                chat_messages.append(tool_result_message(call_id, f"Unknown tool: {name}"))

        return [text_message(last_code)]


agent = CoderAgent()
app   = agent.app

if __name__ == "__main__":
    print(f"[CoderAgent] Starting on port {PORT}...")
    agent.serve(PORT)
