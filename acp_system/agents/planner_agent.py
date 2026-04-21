"""
PlannerAgent — ACP Server on port 9001  [TRUE AGENT]

Receives: ACP Run with text message (the coding task)
Returns:  ACP Run with text message (the technical plan)

True agent loop:
  1. Groq decides which algorithms to explore
  2. Calls consider_approach() → gets real complexity/tradeoff analysis
  3. Compares evaluations and decides the best
  4. Calls finish() with the final numbered plan
"""
from __future__ import annotations

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from groq_setup.infer import generate, groq_chat, get_tool_call, tool_result_message

from shared.base_agent import BaseACPAgent
from shared.models import (
    AgentCapabilities, AgentManifest, Message,
    extract_text, text_message,
)

PORT           = 9001
MAX_ITERATIONS = 8

MANIFEST = AgentManifest(
    name="PlannerAgent",
    description="True agent: evaluates multiple algorithmic approaches then produces the best technical plan.",
    version="2.0.0",
    capabilities=AgentCapabilities(streaming=True),
)

SYSTEM = """\
You are a senior software architect. Your job is to produce the best possible
technical plan for a Python coding task.

You have two tools:
  consider_approach(approach, reasoning) — evaluates a specific algorithm,
                                           returns complexity analysis + tradeoffs
  finish(plan)                           — submits your final numbered plan

Process:
1. Call consider_approach() for 1-2 candidate algorithms
2. Compare the evaluations and decide which is best
3. Call finish() with a clear, numbered, developer-ready plan that includes:
   chosen algorithm, data structures, step-by-step logic, edge cases, test cases

Rules:
- Evaluate at least one approach before finishing
- You MUST call finish() as your final action"""

PLANNER_TOOLS = [
    {"type": "function", "function": {
        "name": "consider_approach",
        "description": "Evaluate a specific algorithmic approach. Returns complexity analysis and tradeoffs.",
        "parameters": {"type": "object",
            "properties": {
                "approach":  {"type": "string", "description": "Algorithm name, e.g. 'two-pointer'"},
                "reasoning": {"type": "string", "description": "Why you think this approach might be suitable"},
            },
            "required": ["approach", "reasoning"]},
    }},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Submit the final technical plan. Call after evaluating approaches.",
        "parameters": {"type": "object",
            "properties": {"plan": {"type": "string", "description": "The complete numbered technical plan"}},
            "required": ["plan"]},
    }},
]


def _evaluate_approach(approach: str, reasoning: str, task: str) -> str:
    return generate(
        f"Task: '{task}'\nEvaluate the '{approach}' approach.\n"
        f"Provide: time complexity, space complexity, key steps, edge cases, pros/cons. Max 150 words.",
        system="You are a software architect. Evaluate algorithmic approaches concisely.",
        max_tokens=300,
    )


class PlannerAgent(BaseACPAgent):
    def __init__(self):
        super().__init__(MANIFEST)

    async def handle(self, messages: list[Message], run_id: str) -> list[Message]:
        task = extract_text(messages)
        print(f"[PlannerAgent] Starting agent loop for: {task[:80]}...")

        chat_messages = [{"role": "user", "content": (
            f"Task: {task}\n\n"
            "Evaluate 1-2 algorithmic approaches using consider_approach(), "
            "then call finish() with the best plan."
        )}]
        final_plan = ""

        for iteration in range(MAX_ITERATIONS):
            assistant_msg = groq_chat(chat_messages, PLANNER_TOOLS, SYSTEM, "required", 1500)
            chat_messages.append(assistant_msg)

            tc = get_tool_call(assistant_msg)
            if tc is None:
                break
            name, args, call_id = tc

            if name == "consider_approach":
                print(f"[PlannerAgent] Evaluating: {args['approach']}")
                result = _evaluate_approach(args["approach"], args["reasoning"], task)
                chat_messages.append(tool_result_message(call_id, result))

            elif name == "finish":
                final_plan = args["plan"]
                print(f"[PlannerAgent] Plan done ({len(final_plan)} chars, {iteration+1} iterations)")
                chat_messages.append(tool_result_message(call_id, "accepted"))
                break

            else:
                chat_messages.append(tool_result_message(call_id, f"Unknown tool: {name}"))

        return [text_message(final_plan)]


agent = PlannerAgent()
app   = agent.app

if __name__ == "__main__":
    print(f"[PlannerAgent] Starting on port {PORT}...")
    agent.serve(PORT)
