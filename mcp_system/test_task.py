"""
test_task.py — End-to-end test for the MCP AgentTeam system.
Usage: python3.12 test_task.py ["optional custom task"]

The three MCP servers must already be running (use run_servers.py first).
"""
from __future__ import annotations

import asyncio
import json
import sys
import textwrap

from boss import solve


def banner(title: str) -> None:
    width = 70
    print("\n" + "─" * width)
    print(f"  {title}")
    print("─" * width)


async def main() -> None:
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else \
        "Write a Python function that merges two sorted lists"

    banner(f"MCP AgentTeam — Task")
    print(f"  {task}\n")

    try:
        result = await solve(task)
    except Exception as exc:
        print(f"\n  ERROR: {exc}")
        raise

    banner("Final Implementation")
    print(textwrap.indent(result["implementation"], "  "))

    banner("Review Verdict")
    review = result["review"]
    try:
        parsed = json.loads(review.strip())
        review = json.dumps(parsed, indent=2)
    except (json.JSONDecodeError, ValueError):
        pass
    print(textwrap.indent(review, "  "))

    print("\n" + "─" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
