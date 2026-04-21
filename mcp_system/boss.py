"""
Boss — MCP client + Groq orchestrator
Connects to three MCP worker servers, drives plan→code→review pipeline
using Groq function calling (llama-3.3-70b-versatile).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from fastmcp import Client

from groq_setup.infer import groq_chat, get_tool_call, tool_result_message

PLANNER_URL  = "http://localhost:8101/mcp"
CODER_URL    = "http://localhost:8102/mcp"
REVIEWER_URL = "http://localhost:8103/mcp"

SYSTEM = """\
You are an autonomous engineering manager orchestrating a software pipeline.
You have four tools:

  plan(task)                           — PlannerAgent: creates a numbered technical plan
  write_and_test_code(plan, feedback)  — CoderAgent: writes & self-tests Python code
  review_code(code, original_task)     — ReviewerAgent: reviews code, returns JSON verdict
  finish(status)                       — Signal pipeline complete

Workflow:
1. Call plan() with the task
2. Call write_and_test_code() with the plan
3. Call review_code() with the code and the original task
4. If verdict="pass"  → call finish(status="passed")
5. If verdict="fail"  → call write_and_test_code() again with plan + reviewer issues as feedback
6. After 3 total coding attempts → call finish(status="best_effort")

Rules:
- Always plan before coding, always review before finishing
- You MUST call finish() as your final action"""

BOSS_TOOLS = [
    {"type": "function", "function": {
        "name": "plan",
        "description": "Send the task to PlannerAgent to produce a step-by-step technical plan. Call this first.",
        "parameters": {"type": "object",
            "properties": {"task": {"type": "string", "description": "The coding task to plan"}},
            "required": ["task"]},
    }},
    {"type": "function", "function": {
        "name": "write_and_test_code",
        "description": "Send the plan to CoderAgent. It writes, runs, and self-corrects Python code.",
        "parameters": {"type": "object",
            "properties": {
                "plan": {"type": "string", "description": "The technical plan to implement"},
                "feedback": {"type": "string", "description": "Reviewer issues to fix. Omit on first call."},
            },
            "required": ["plan"]},
    }},
    {"type": "function", "function": {
        "name": "review_code",
        "description": "Send code to ReviewerAgent for quality review. Returns a JSON verdict.",
        "parameters": {"type": "object",
            "properties": {
                "code": {"type": "string"},
                "original_task": {"type": "string"},
            },
            "required": ["code", "original_task"]},
    }},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Signal that the pipeline is complete.",
        "parameters": {"type": "object",
            "properties": {"status": {"type": "string", "description": "'passed' or 'best_effort'"}},
            "required": ["status"]},
    }},
]


def _elapsed(start: float) -> str:
    return f"{int((time.time() - start) * 1000)}ms"


async def solve(task: str) -> dict:
    print(f"\n{'─'*60}\n  Task: {task}\n{'─'*60}\n")

    async with (
        Client(PLANNER_URL)  as planner,
        Client(CODER_URL)    as coder,
        Client(REVIEWER_URL) as reviewer,
    ):
        tool_registry = {
            "plan":                planner,
            "write_and_test_code": coder,
            "review_code":         reviewer,
        }

        messages    = [{"role": "user", "content": f"Task: {task}"}]
        last_code   = ""
        last_review = ""
        total_start = time.time()

        for step in range(12):
            t0 = time.time()
            assistant_msg = await asyncio.to_thread(
                groq_chat, messages, BOSS_TOOLS, SYSTEM, "required", 1024
            )
            messages.append(assistant_msg)

            tc = get_tool_call(assistant_msg)
            if tc is None:
                print("  [Boss] No tool call — stopping")
                break
            name, args, call_id = tc

            print(f"  [Boss → {name}]  ({_elapsed(t0)})")

            if name == "finish":
                print(f"  [Boss] Pipeline complete — status={args.get('status')}")
                messages.append(tool_result_message(call_id, "done"))
                break

            server = tool_registry.get(name)
            if server is None:
                messages.append(tool_result_message(call_id, f"ERROR: Unknown tool '{name}'"))
                continue

            t1 = time.time()
            mcp_result = await server.call_tool(name, args)
            items = mcp_result.content if hasattr(mcp_result, "content") else mcp_result
            tool_result = "".join(item.text for item in items if hasattr(item, "text"))

            print(f"  [{name} → Boss]  {len(tool_result)} chars  ({_elapsed(t1)})")

            if name == "write_and_test_code":
                last_code = tool_result
            elif name == "review_code":
                last_review = tool_result
                try:
                    verdict = json.loads(tool_result).get("verdict", "?")
                    print(f"  [Verdict] {verdict.upper()}")
                except Exception:
                    pass

            messages.append(tool_result_message(call_id, tool_result))

        print(f"\n  Total pipeline time: {_elapsed(total_start)}")
        return {"implementation": last_code, "review": last_review}


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else \
        "Write a Python function that merges two sorted lists"

    result = asyncio.run(solve(task))

    print(f"\n{'═'*60}\n  IMPLEMENTATION\n{'═'*60}")
    print(result["implementation"])

    print(f"\n{'═'*60}\n  REVIEW\n{'═'*60}")
    try:
        print(json.dumps(json.loads(result["review"]), indent=2))
    except Exception:
        print(result["review"])
