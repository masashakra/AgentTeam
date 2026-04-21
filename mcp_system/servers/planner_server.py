"""
PlannerAgent — MCP Server on port 8101  [TRUE AGENT]
Exposes one tool: plan(task) → step-by-step technical plan

True agent loop:
  1. Groq decides which algorithmic approaches to explore
  2. Calls consider_approach() for each candidate → real complexity/tradeoff analysis
  3. Compares results and decides on the best approach
  4. Calls finish() with the final plan
"""
from __future__ import annotations

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastmcp import FastMCP

from groq_setup.infer import generate, groq_chat, get_tool_call, tool_result_message

MAX_ITERATIONS = 8

mcp = FastMCP("PlannerAgent")

SYSTEM = """\
You are a senior software architect. Your job is to produce the best possible
technical plan for a Python coding task.

You have two tools:
  consider_approach(approach, reasoning) — evaluates a specific algorithm/approach,
                                           returns complexity analysis and tradeoffs
  finish(plan)                           — submits your final numbered plan

Process:
1. Call consider_approach() for 1-2 candidate algorithms you think could work
2. Based on the evaluations, decide which is best
3. Call finish() with a clear, numbered, developer-ready plan

Rules:
- Always evaluate at least one approach before finishing
- Your plan must include: chosen algorithm, data structures, step-by-step logic,
  edge cases to handle, and suggested test cases
- You MUST call finish() as your final action"""

PLANNER_TOOLS = [
    {"type": "function", "function": {
        "name": "consider_approach",
        "description": "Evaluate a specific algorithmic approach. Returns complexity, steps, and tradeoffs.",
        "parameters": {"type": "object",
            "properties": {
                "approach":  {"type": "string", "description": "Algorithm name, e.g. 'two-pointer'"},
                "reasoning": {"type": "string", "description": "Why you think this approach might work"},
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
        f"Task: '{task}'\n\n"
        f"Evaluate the '{approach}' approach.\n"
        f"Provide: time complexity, space complexity, key implementation steps, "
        f"edge cases it handles, pros and cons. Be concise (max 200 words).",
        system="You are a software architect. Evaluate algorithmic approaches concisely.",
        max_tokens=400,
    )


@mcp.tool()
def plan(task: str) -> str:
    """
    Autonomously explore algorithmic approaches and produce a step-by-step technical plan.

    Args:
        task: The coding task to plan.

    Returns:
        A numbered technical plan as plain text.
    """
    print(f"[PlannerAgent] Starting agent loop for: {task[:80]}...")

    messages = [{"role": "user", "content": (
        f"Task: {task}\n\n"
        "Explore 1-2 algorithmic approaches using consider_approach(), "
        "then call finish() with the best plan."
    )}]
    final_plan = ""

    for iteration in range(MAX_ITERATIONS):
        assistant_msg = groq_chat(messages, PLANNER_TOOLS, SYSTEM, "required", 1500)
        messages.append(assistant_msg)

        tc = get_tool_call(assistant_msg)
        if tc is None:
            break
        name, args, call_id = tc

        if name == "consider_approach":
            print(f"[PlannerAgent] Evaluating approach: {args['approach']}")
            result = _evaluate_approach(args["approach"], args["reasoning"], task)
            print(f"[PlannerAgent] Got evaluation ({len(result)} chars)")
            messages.append(tool_result_message(call_id, result))

        elif name == "finish":
            final_plan = args["plan"]
            print(f"[PlannerAgent] Plan finalised ({len(final_plan)} chars, {iteration+1} iterations)")
            messages.append(tool_result_message(call_id, "accepted"))
            break

        else:
            messages.append(tool_result_message(call_id, f"Unknown tool: {name}"))

    return final_plan


if __name__ == "__main__":
    print("[PlannerAgent] Starting on port 8101...")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8101)
