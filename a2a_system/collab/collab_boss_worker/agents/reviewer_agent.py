"""
Reviewer Agent — port 8003
Reasons about code quality before issuing a structured pass/fail verdict.
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
    AgentCard, AgentCapabilities, AgentSkill, Artifact,
    Message, extract_data, extract_text, text_artifact,
)

CARD = AgentCard(
    name="Reviewer Agent",
    description="Reasons about code quality then returns a structured pass/fail verdict.",
    url="http://localhost:8003",
    version="3.0.0",
    capabilities=AgentCapabilities(streaming=True),
    skills=[AgentSkill(
        id="review", name="review",
        description="Review Python code for correctness, style, and edge-case handling.",
        inputModes=["text", "data"], outputModes=["text"],
    )],
)

SYSTEM = """\
You are a meticulous Python code reviewer. Review the provided code and respond
with a JSON object in this exact format (no markdown, raw JSON only):
{
  "verdict": "pass" or "fail",
  "summary": "<one-sentence summary>",
  "issues": ["<issue 1>", ...],
  "suggestions": ["<suggestion 1>", ...]
}
verdict is "pass" only when the code is correct, handles edge cases, uses type
hints, and has docstrings. Otherwise "fail" with specific issues listed."""

THINK_SUFFIX = """

Before writing your verdict, reason through:
- If debug findings are provided, what issues did the tests uncover?
- Does the code correctly implement what the task asked for?
- Are there any logic errors, off-by-one errors, or missing edge cases?
- Are type hints and docstrings present on every function?
- What specific changes would you require before passing this?
Output your analysis as 3-5 bullet points. Do NOT write the JSON verdict yet."""

ACT_PREFIX = "Good. Now write your final JSON verdict based on that analysis. Raw JSON only, no markdown."


class ReviewerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(CARD)

    async def handle(self, message: Message, task_id: str) -> list[Artifact]:
        code = extract_text(message)
        data = extract_data(message)
        original_task = data.get("original_task", "")
        debug_report = data.get("debug_report", "")

        user_content = f"Original task: {original_task}\n\nCode to review:\n{code}"
        if debug_report:
            user_content += f"\n\nDebug report from testing:\n{debug_report}"

        # ── Turn 1: Think ──────────────────────────────────────────────────
        thinking = await asyncio.to_thread(
            groq_complete,
            [{"role": "user", "content": user_content + THINK_SUFFIX}],
            SYSTEM, 512,
        )

        # ── Turn 2: Act ────────────────────────────────────────────────────
        review_text = await asyncio.to_thread(
            groq_complete,
            [
                {"role": "user",      "content": user_content},
                {"role": "assistant", "content": thinking},
                {"role": "user",      "content": ACT_PREFIX},
            ],
            SYSTEM, 1024,
        )

        return [text_artifact("review", review_text)]


agent = ReviewerAgent()
app = agent.app

if __name__ == "__main__":
    uvicorn.run("agents.reviewer_agent:app", host="0.0.0.0", port=8003, reload=False)
