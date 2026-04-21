"""
TestGeneratorAgent — port 8014
Called ONCE at session start to generate a test suite for the coding task.
Uses think→act pattern (groq_complete, 2 turns). Stateless.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent.parent.parent))

import uvicorn

from groq_setup.infer import groq_complete

from shared.base_agent import BaseAgent
from shared.models import (
    AgentCard, AgentCapabilities, AgentSkill, Artifact,
    Message, extract_text, extract_data, text_artifact,
)

AGENT_PORT = int(os.getenv("TEST_GENERATOR_PORT", "8014"))
AGENT_HOST = os.getenv("AGENT_HOST", "localhost")
AGENT_URL = os.getenv("TEST_GENERATOR_URL", f"http://{AGENT_HOST}:{AGENT_PORT}")

CARD = AgentCard(
    name="Test Generator Agent",
    description="Generates a test suite for a coding task before any coding begins.",
    url=AGENT_URL,
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True, pushNotifications=False),
    skills=[AgentSkill(
        id="generate_tests",
        name="generate_tests",
        description="Generate a JSON test suite for a given coding task.",
        inputModes=["text", "data"],
        outputModes=["text"],
    )],
)

SYSTEM = """\
You are a senior QA engineer specialized in writing comprehensive test suites.
Your job is to generate test cases that cover normal cases, edge cases,
and inputs that could break naive implementations."""

THINK_SUFFIX = """

Before writing tests, reason through:
What are the normal cases? What are the edge cases? What inputs could
break a naive implementation? Output 3-5 bullet points of reasoning.
Do NOT write tests yet."""

ACT_PROMPT = (
    "Good. Now write the test suite as a JSON array. "
    "Each test must have: input (the function arguments as a list), "
    "expected_output, description. "
    "Output raw JSON only, no markdown, no explanation."
)


class TestGeneratorAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(CARD)

    async def handle(self, message: Message, task_id: str) -> list[Artifact]:
        data = extract_data(message)
        task = data.get("task", extract_text(message))
        task_text = f"Task: {task}"

        # ── Turn 1: Think ──────────────────────────────────────────────────────
        thinking = await asyncio.to_thread(
            groq_complete,
            [{"role": "user", "content": task_text + THINK_SUFFIX}],
            SYSTEM,
            1024,
        )

        # ── Turn 2: Act ────────────────────────────────────────────────────────
        test_suite_raw = await asyncio.to_thread(
            groq_complete,
            [
                {"role": "user",      "content": task_text + THINK_SUFFIX},
                {"role": "assistant", "content": thinking},
                {"role": "user",      "content": ACT_PROMPT},
            ],
            SYSTEM,
            1024,
        )

        # Strip markdown fences if present
        stripped = test_suite_raw.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            inner = lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
            stripped = "\n".join(inner).strip()

        # Validate JSON; fall back to empty array on parse error
        try:
            parsed = json.loads(stripped)
            if not isinstance(parsed, list):
                parsed = []
        except json.JSONDecodeError:
            parsed = []

        return [text_artifact("test_suite", json.dumps(parsed, indent=2))]


agent = TestGeneratorAgent()
app = agent.app

if __name__ == "__main__":
    uvicorn.run("agents.test_generator_agent:app", host="0.0.0.0", port=8014, reload=False)
