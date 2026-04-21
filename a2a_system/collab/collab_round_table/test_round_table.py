"""
test_round_table.py — End-to-end test for the Round Table scenario.

Sends the canonical LCS task and prints:
  - Final code
  - Validation report
  - Pass rate summary

All 8 agents must already be running (use run_round_table.py first,
OR this script starts the orchestrator which requires agents to be up).

Usage:
  # Option A: run agents separately, then run this
  cd collab_round_table
  python3 run_round_table.py &
  python3 test_round_table.py

  # Option B: run everything together
  cd collab_round_table
  python3 run_round_table.py  # runs orchestrator automatically
"""
from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

TASK = (
    "Write a Python function that finds the longest common subsequence "
    "of two strings"
)


def _banner(title: str) -> None:
    width = 70
    print("\n" + "─" * width)
    print(f"  {title}")
    print("─" * width)


def _print_state(state: dict) -> None:
    agent_outputs = state.get("agent_outputs", {})
    session_id = state.get("session_id", "?")
    reason = state.get("termination_reason", "?")
    total_rounds = max(0, state.get("round", 1) - 1)

    _banner(f"Round Table Test — Task")
    print(f"  {TASK}")

    _banner("Session Summary")
    print(f"  Session ID         : {session_id}")
    print(f"  Termination reason : {reason}")
    print(f"  Total rounds       : {total_rounds}")
    print(f"  Final pass rate    : {agent_outputs.get('final_pass_rate', 'N/A')}")

    _banner("Final Code (CoderAgentRT)")
    code = agent_outputs.get("Coder", "# No code generated")
    print(textwrap.indent(code, "  "))

    _banner("Architect Design Approach")
    print(textwrap.indent(agent_outputs.get("Architect", "(none)"), "  "))

    _banner("Debugger Fix / Analysis")
    print(textwrap.indent(agent_outputs.get("Debugger", "(none)"), "  "))

    _banner("Tester Feedback")
    print(textwrap.indent(agent_outputs.get("Tester", "(none)"), "  "))

    _banner("Validation Report")
    report_raw = agent_outputs.get("validation_report", "{}")
    try:
        report = json.loads(report_raw)
        print(textwrap.indent(json.dumps(report, indent=2), "  "))
        # Pass rate summary
        _banner("Pass Rate Summary")
        pr = agent_outputs.get("final_pass_rate", "?")
        pylint = report.get("pylint_score", "?")
        complexity = report.get("complexity", "?")
        print(f"  Final pass rate : {pr}")
        print(f"  Pylint score    : {pylint}/10")
        print(f"  Complexity      : {complexity}")
        issues = report.get("issues", [])
        if issues:
            print(f"  Issues ({len(issues)}):")
            for issue in issues:
                print(f"    - {issue}")
        suggestions = report.get("suggestions", [])
        if suggestions:
            print(f"  Suggestions ({len(suggestions)}):")
            for sug in suggestions:
                print(f"    - {sug}")
    except Exception:
        print(textwrap.indent(report_raw, "  "))

    print()
    print(f"  Full logs: collab_round_table/logs/  (session_id={session_id})")
    print("─" * 70 + "\n")


async def run_test() -> None:
    _banner("Round Table Test Client")
    print(f"  Task: {TASK}\n")

    from orchestrator import run as run_orchestrator

    try:
        final_state = await run_orchestrator(TASK, max_rounds=4)
        _print_state(final_state)
    except Exception as exc:
        print(f"\nERROR: {exc}")
        print("Make sure all agents are running first (python3 run_round_table.py)")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_test())
