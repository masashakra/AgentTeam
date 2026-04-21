"""
Boss Agent — port 8000
True A2A orchestrator: uses Groq function calling to drive plan→code→review.
Uses agent discovery — no hardcoded URLs. Discovers workers by skill ID at runtime.

CHANGES FOR LANGGRAPH INTEGRATION (marked with # [LG]):
  1. handle() now accepts test_suite and round from orchestrator state
  2. finish() sets self._last_status so orchestrator can read termination signal
  3. No logic changes — Boss still runs its full internal A2A loop autonomously
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent.parent.parent))

import httpx
import uvicorn

from groq_setup.infer import groq_chat, get_tool_call, tool_result_message

from shared.base_agent import BaseAgent, _auth_headers
from shared.discover import find_agent_by_name
from shared.logger import elapsed_ms, log_reply, log_send, log_session_start, log_verdict, start_timer
from shared.models import (
    AgentCard, AgentCapabilities, AgentSkill, Artifact, DataPart, Message,
    Task, TaskSendParams, TaskState, TextPart,
    extract_data, extract_text, get_artifact_text, text_artifact,
)

MAX_TOOL_CALLS = 10

CARD = AgentCard(
    name="Boss Agent",
    description="Autonomous A2A orchestrator: drives plan→code→review via discovery.",
    url="http://localhost:8000",
    version="4.1.0",                          # [LG] bumped version
    capabilities=AgentCapabilities(streaming=True, pushNotifications=True),
    skills=[AgentSkill(
        id="solve", name="solve",
        description="Accept a coding task and return working, reviewed Python code.",
        inputModes=["text"], outputModes=["text"],
    )],
)

BOSS_SYSTEM = """\
You are an autonomous engineering manager orchestrating a software delivery pipeline.
You have four tools:

  call_planner(task)                  — Get a technical plan from the Planner
  call_coder(plan, feedback?)         — Get implemented code from the Coder
  call_reviewer(code, original_task)  — Get a code review from the Reviewer
  finish(status)                      — Signal completion

Workflow:
1. call_planner to get a technical plan
2. call_coder with that plan
3. call_reviewer with the code and original task
4. If verdict="pass" → call finish(status="passed")
5. If verdict="fail" → call_coder again with the plan AND reviewer feedback
6. After 3 total coder attempts → call finish(status="best_effort")

Rules:
- Always call call_planner exactly once at the start
- Never call finish without at least one review result
- Always pass feedback to call_coder on retries
- You MUST call finish() as your final action"""

BOSS_TOOLS = [
    {"type": "function", "function": {
        "name": "call_planner",
        "description": "Send task to PlannerAgent to produce a technical plan.",
        "parameters": {"type": "object",
            "properties": {"task": {"type": "string"}},
            "required": ["task"]},
    }},
    {"type": "function", "function": {
        "name": "call_coder",
        "description": "Send plan to CoderAgent to produce Python code.",
        "parameters": {"type": "object",
            "properties": {
                "plan": {"type": "string"},
                "feedback": {"type": "string", "description": "Reviewer feedback. Omit on first call."},
            },
            "required": ["plan"]},
    }},
    {"type": "function", "function": {
        "name": "call_reviewer",
        "description": "Send code to ReviewerAgent for quality review.",
        "parameters": {"type": "object",
            "properties": {
                "code": {"type": "string"},
                "original_task": {"type": "string"},
            },
            "required": ["code", "original_task"]},
    }},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Signal task complete.",
        "parameters": {"type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"]},
    }},
]


async def _post(client: httpx.AsyncClient, url: str, params: TaskSendParams) -> Task:
    headers = {**_auth_headers(), "X-Sender": "BossAgent"}
    resp = await client.post(
        url, json=params.model_dump(mode="json"), headers=headers, timeout=120.0
    )
    resp.raise_for_status()
    return Task.model_validate(resp.json())


class BossAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(CARD)
        self._last_status: str = ""    # [LG] expose termination signal to orchestrator

    async def handle(self, message: Message, task_id: str) -> list[Artifact]:
        task_description = extract_text(message)

        # [LG] Read orchestration context passed by LangGraph (round number, test suite)
        # Boss uses these internally — LangGraph never sees the contents
        data = extract_data(message)
        current_round = data.get("round", 1)
        test_suite    = data.get("test_suite", [])

        log_session_start(f"Round {current_round}: {task_description}")

        messages = [{"role": "user", "content": f"Task: {task_description}"}]
        last_code  = ""
        last_review = ""

        # Discover workers at runtime — no hardcoded URLs
        planner_card  = await find_agent_by_name("Planner Agent")
        coder_card    = await find_agent_by_name("Coder Agent")
        reviewer_card = await find_agent_by_name("Reviewer Agent")

        planner_url  = f"{planner_card.url}/tasks/send"
        coder_url    = f"{coder_card.url}/tasks/send"
        reviewer_url = f"{reviewer_card.url}/tasks/send"

        async with httpx.AsyncClient() as http:
            for step in range(MAX_TOOL_CALLS):

                start_timer("boss-groq")
                assistant_msg = await asyncio.to_thread(
                    groq_chat, messages, BOSS_TOOLS, BOSS_SYSTEM, "required", 1024
                )
                messages.append(assistant_msg)

                tc = get_tool_call(assistant_msg)
                if tc is None:
                    break
                name, args, call_id = tc

                if name == "finish":
                    if last_code:
                        # [LG] Store status so orchestrator can read termination reason
                        self._last_status = args.get("status", "completed")
                        messages.append(tool_result_message(call_id, "accepted"))
                        break
                    tool_result = "ERROR: Call call_planner and call_coder before finish."

                elif name == "call_planner":
                    plan_tid = f"{task_id}-plan"
                    log_send("BossAgent", "PlannerAgent", plan_tid, "skill='plan'", payload=args["task"])
                    start_timer(plan_tid)
                    plan_task = await _post(http, planner_url, TaskSendParams(
                        id=plan_tid,
                        message=Message(role="user", parts=[TextPart(text=args["task"])]),
                    ))
                    t = elapsed_ms(plan_tid)
                    if plan_task.status.state == TaskState.failed:
                        tool_result = "ERROR: Planner failed"
                    else:
                        tool_result = get_artifact_text(plan_task, "technical_plan")
                        log_reply("PlannerAgent", "BossAgent", plan_tid,
                                  plan_task.status.state.value, "technical_plan",
                                  payload=tool_result, elapsed=t)

                elif name == "call_coder":
                    code_tid = f"{task_id}-code-{step}"
                    feedback = args.get("feedback", "")
                    msg_parts: list = [TextPart(text=args["plan"])]
                    if feedback:
                        msg_parts.append(DataPart(data={"feedback": feedback}))
                    log_send("BossAgent", "CoderAgent", code_tid,
                             "skill='code'" + ("  +feedback" if feedback else ""), payload=args["plan"])
                    start_timer(code_tid)
                    code_task = await _post(http, coder_url, TaskSendParams(
                        id=code_tid,
                        message=Message(role="user", parts=msg_parts),
                    ))
                    t = elapsed_ms(code_tid)
                    if code_task.status.state == TaskState.failed:
                        tool_result = "ERROR: Coder failed"
                    else:
                        tool_result = get_artifact_text(code_task, "implementation")
                        last_code = tool_result
                        log_reply("CoderAgent", "BossAgent", code_tid,
                                  code_task.status.state.value, "implementation",
                                  payload=tool_result, elapsed=t)

                elif name == "call_reviewer":
                    review_tid = f"{task_id}-review-{step}"
                    log_send("BossAgent", "ReviewerAgent", review_tid, "skill='review'", payload=args["code"])
                    start_timer(review_tid)
                    review_task = await _post(http, reviewer_url, TaskSendParams(
                        id=review_tid,
                        message=Message(role="user", parts=[
                            TextPart(text=args["code"]),
                            DataPart(data={"original_task": args.get("original_task", "")}),
                        ]),
                    ))
                    t = elapsed_ms(review_tid)
                    if review_task.status.state == TaskState.failed:
                        tool_result = "ERROR: Reviewer failed"
                    else:
                        tool_result = get_artifact_text(review_task, "review")
                        last_review = tool_result
                        log_reply("ReviewerAgent", "BossAgent", review_tid,
                                  review_task.status.state.value, "review",
                                  payload=tool_result, elapsed=t)
                        try:
                            raw = last_review.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                            review_data = json.loads(raw)
                            log_verdict(review_data.get("verdict", "fail"),
                                        review_data.get("issues", []),
                                        review_data.get("suggestions", []), step)
                        except Exception:
                            pass
                else:
                    tool_result = f"Unknown tool: {name}"

                messages.append(tool_result_message(call_id, tool_result))

        if not last_code:
            raise RuntimeError("Agent loop ended without producing code.")

        return [
            text_artifact("implementation", last_code, index=0),
            text_artifact("review", last_review, index=1),
        ]


agent = BossAgent()
app = agent.app

if __name__ == "__main__":
    uvicorn.run("agents.boss_agent:app", host="0.0.0.0", port=8000, reload=False)