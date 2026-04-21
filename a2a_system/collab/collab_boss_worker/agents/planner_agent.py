"""
Planner Agent — port 8001
Reasons about the task before producing a technical plan (2-turn think→act).
Uses Groq (llama-3.3-70b-versatile) via groq_setup.
"""
from __future__ import annotations

import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent.parent.parent))

import uvicorn

from groq_setup.infer import groq_complete

from shared.base_agent import BaseAgent
from shared.models import (
    AgentCard, AgentCapabilities, AgentSkill, Artifact, Message, extract_text, text_artifact,
)

CARD = AgentCard(
    name="Planner Agent",
    description="Reasons about a coding task then produces a step-by-step technical plan.",
    url="http://localhost:8001",
    version="3.0.0",
    capabilities=AgentCapabilities(streaming=True),
    skills=[AgentSkill(
        id="plan", name="plan",
        description="Break a coding task into a numbered, step-by-step technical plan.",
        inputModes=["text"], outputModes=["text"],
    )],
)

SYSTEM = """\
You are a senior software architect. Given a coding task, produce a clear,
numbered, step-by-step technical plan that a developer can follow to implement
the solution. Include:
- Data structures needed
- Algorithm outline (pseudocode where helpful)
- Edge cases to handle
- Suggested function signatures
Keep the plan concise but complete."""

THINK_SUFFIX = """

Before writing the plan, reason through:
- What are the key technical challenges?
- What edge cases must the plan address?
- What data structures and algorithms are most appropriate?
Output your reasoning as 3-5 bullet points. Do NOT write the plan yet."""

ACT_PREFIX = "Good. Now write the complete technical plan based on your analysis above."


class PlannerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(CARD)

    async def handle(self, message: Message, task_id: str) -> list[Artifact]:
        task_description = extract_text(message)
        task_text = f"Task: {task_description}"

        # ── Turn 1: Think ──────────────────────────────────────────────────
        thinking = await asyncio.to_thread(
            groq_complete,
            [{"role": "user", "content": task_text + THINK_SUFFIX}],
            SYSTEM, 512,
        )

        # ── Turn 2: Act ────────────────────────────────────────────────────
        plan_text = await asyncio.to_thread(
            groq_complete,
            [
                {"role": "user",      "content": task_text},
                {"role": "assistant", "content": thinking},
                {"role": "user",      "content": ACT_PREFIX},
            ],
            SYSTEM, 2048,
        )

        return [text_artifact("technical_plan", plan_text)]


agent = PlannerAgent()
app = agent.app

if __name__ == "__main__":
    uvicorn.run("agents.planner_agent:app", host="0.0.0.0", port=8001, reload=False)
