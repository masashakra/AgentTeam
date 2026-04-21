"""
BossAgent — ACP Server on port 9000  [TRUE AGENT]

Receives: ACP Run with text message (the coding task)
Returns:  ACP Run with text message (final code) + JSON message (review verdict)

True agent loop (Groq function-calling):
  Groq autonomously decides which workers to call and in what order.
  It observes each worker's output before deciding the next action.
  Loop ends when Groq calls finish() or MAX_TOOL_CALLS is exhausted.
"""
from __future__ import annotations

import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import httpx

from groq_setup.infer import groq_chat, get_tool_call, tool_result_message

from shared.base_agent import BaseACPAgent
from shared.models import (
    AgentCapabilities, AgentManifest, Message, Run,
    extract_text, get_run_json, get_run_text,
    json_message, text_message,
)

PORT          = 9000
MAX_TOOL_CALLS = 12

PLANNER_URL  = "http://localhost:9001"
CODER_URL    = "http://localhost:9002"
REVIEWER_URL = "http://localhost:9003"

MANIFEST = AgentManifest(
    name="BossAgent",
    description="True agent: orchestrates Planner→Coder→Reviewer using Groq function calling.",
    version="2.0.0",
    capabilities=AgentCapabilities(streaming=True),
)

SYSTEM = """\
You are an engineering manager orchestrating a team of specialist agents to solve coding tasks.

You have four tools:
  call_planner(task)                — sends task to PlannerAgent, returns technical plan
  call_coder(plan, feedback)        — sends plan to CoderAgent, returns Python implementation
  call_reviewer(code)               — sends code to ReviewerAgent, returns pass/fail JSON verdict
  finish(status)                    — ends the session ("passed" or "best_effort")

Standard workflow:
1. call_planner with the original task → get a technical plan
2. call_coder with that plan → get Python code
3. call_reviewer with that code → get verdict
4. If verdict is "fail": call_coder again with the plan AND the reviewer feedback → get fixed code
5. call_reviewer again on the fixed code
6. When verdict is "pass" (or after 2 coder attempts), call finish()

Rules:
- Always start with call_planner
- Always call call_reviewer after getting code
- Never call finish before getting at least one review
- You MUST call finish() as your final action"""

BOSS_TOOLS = [
    {"type": "function", "function": {
        "name": "call_planner",
        "description": "Send the coding task to PlannerAgent. Returns a detailed technical plan.",
        "parameters": {"type": "object",
            "properties": {"task": {"type": "string", "description": "The original coding task to plan"}},
            "required": ["task"]},
    }},
    {"type": "function", "function": {
        "name": "call_coder",
        "description": "Send a plan to CoderAgent. Optionally include reviewer feedback for a retry.",
        "parameters": {"type": "object",
            "properties": {
                "plan":     {"type": "string", "description": "The technical plan to implement"},
                "feedback": {"type": "string", "description": "Optional reviewer feedback JSON string for retry"},
            },
            "required": ["plan"]},
    }},
    {"type": "function", "function": {
        "name": "call_reviewer",
        "description": "Send code to ReviewerAgent. Returns JSON verdict with pass/fail + issues.",
        "parameters": {"type": "object",
            "properties": {"code": {"type": "string", "description": "The Python code to review"}},
            "required": ["code"]},
    }},
    {"type": "function", "function": {
        "name": "finish",
        "description": "End the session after reviewing. Call when done.",
        "parameters": {"type": "object",
            "properties": {"status": {"type": "string", "description": '"passed" or "best_effort"'}},
            "required": ["status"]},
    }},
]


def _acp_run(url: str, agent_name: str, messages: list[Message]) -> Run:
    payload = {"agent_name": agent_name, "input": [m.model_dump() for m in messages]}
    with httpx.Client(timeout=300) as client:
        resp = client.post(f"{url}/runs", json=payload)
        resp.raise_for_status()
        return Run(**resp.json())


class BossAgent(BaseACPAgent):
    def __init__(self):
        super().__init__(MANIFEST)

    async def handle(self, messages: list[Message], run_id: str) -> list[Message]:
        task = extract_text(messages)
        print(f"[BossAgent] Task: {task[:80]}...")

        chat_messages = [{"role": "user", "content": (
            f"Coding task: {task}\n\n"
            "Start by calling call_planner, then call_coder, then call_reviewer. "
            "Retry coder if needed. Call finish() when done."
        )}]

        last_code   = ""
        last_review = {}
        last_plan   = ""

        for step in range(MAX_TOOL_CALLS):
            assistant_msg = groq_chat(chat_messages, BOSS_TOOLS, SYSTEM, "required", 1000)
            chat_messages.append(assistant_msg)

            tc = get_tool_call(assistant_msg)
            if tc is None:
                print("[BossAgent] No tool call — stopping.")
                break
            name, args, call_id = tc

            # ── call_planner ──────────────────────────────────────────────
            if name == "call_planner":
                task_text = args.get("task", task)
                print(f"[BossAgent] → PlannerAgent ({len(task_text)} chars)")
                try:
                    run = _acp_run(PLANNER_URL, "PlannerAgent", [text_message(task_text)])
                    last_plan = get_run_text(run)
                    print(f"[BossAgent] ← Plan received ({len(last_plan)} chars)")
                    tool_result = last_plan or "ERROR: Planner returned empty plan"
                except Exception as e:
                    tool_result = f"ERROR calling PlannerAgent: {e}"

            # ── call_coder ────────────────────────────────────────────────
            elif name == "call_coder":
                plan         = args.get("plan", last_plan)
                feedback_str = args.get("feedback", "")
                coder_msgs   = [text_message(plan)]
                if feedback_str:
                    try:
                        feedback_data = json.loads(feedback_str)
                    except Exception:
                        feedback_data = {"issues": [feedback_str], "suggestions": []}
                    coder_msgs.append(json_message(feedback_data, name="feedback"))
                print(f"[BossAgent] → CoderAgent (plan={len(plan)} chars, feedback={bool(feedback_str)})")
                try:
                    run = _acp_run(CODER_URL, "CoderAgent", coder_msgs)
                    last_code = get_run_text(run)
                    print(f"[BossAgent] ← Code received ({len(last_code)} chars)")
                    tool_result = last_code or "ERROR: Coder returned empty code"
                except Exception as e:
                    tool_result = f"ERROR calling CoderAgent: {e}"

            # ── call_reviewer ─────────────────────────────────────────────
            elif name == "call_reviewer":
                code = args.get("code", last_code)
                print(f"[BossAgent] → ReviewerAgent ({len(code)} chars)")
                try:
                    reviewer_msgs = [
                        text_message(code),
                        json_message({"task": task}, name="original_task"),
                    ]
                    run = _acp_run(REVIEWER_URL, "ReviewerAgent", reviewer_msgs)
                    last_review = get_run_json(run, name="review")
                    verdict = last_review.get("verdict", "?")
                    print(f"[BossAgent] ← Review: {verdict.upper()} — {last_review.get('summary', '')[:60]}")
                    tool_result = json.dumps(last_review)
                except Exception as e:
                    tool_result = f"ERROR calling ReviewerAgent: {e}"

            # ── finish ────────────────────────────────────────────────────
            elif name == "finish":
                status = args.get("status", "best_effort")
                print(f"[BossAgent] Done — status={status}, code={len(last_code)} chars")
                chat_messages.append(tool_result_message(call_id, "accepted"))
                break

            else:
                tool_result = f"Unknown tool: {name}"

            chat_messages.append(tool_result_message(call_id, tool_result))

        if not last_code:
            return [text_message("ERROR: No code produced"), json_message({"verdict": "fail"}, name="review")]

        return [text_message(last_code), json_message(last_review, name="review")]


agent = BossAgent()
app   = agent.app

if __name__ == "__main__":
    print(f"[BossAgent] Starting on port {PORT}...")
    agent.serve(PORT)
