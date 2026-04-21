"""
orchestrator.py — LangGraph orchestration layer for Boss-Worker Strict scenario.

Responsibilities (LangGraph only):
  - Round management (track current round, max rounds)
  - Node sequencing (what runs and when)
  - Termination logic (done? loop? stop?)
  - Passing orchestration-relevant state between phases

NOT responsible for:
  - What agents say to each other (A2A handles that)
  - Agent discovery (agents handle that on boot)
  - LLM reasoning (each agent handles that internally)

Nodes:
  test_generator_node  — runs once at start, generates test suite
  boss_round_node      — triggers Boss to run one full A2A round
  code_validator_node  — runs once at end, validates final output

Usage:
  python orchestrator.py
  OR import run() and call it from your run_all.py
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Optional

import httpx
from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

# ── URLs ──────────────────────────────────────────────────────────────────────
# These are the only URLs orchestrator knows — just agent entry points.
# All internal A2A communication between agents is invisible to LangGraph.

BOSS_URL           = os.getenv("BOSS_URL",           "http://localhost:8000")
TEST_GENERATOR_URL = os.getenv("TEST_GENERATOR_URL", "http://localhost:8004")
CODE_VALIDATOR_URL = os.getenv("CODE_VALIDATOR_URL", "http://localhost:8005")

MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "3"))


# ── State ─────────────────────────────────────────────────────────────────
# This is ALL LangGraph knows about. No message content, no A2A payloads.

class BossWorkerState(TypedDict):
    session_id:         str
    task:               str
    round:              int
    max_rounds:         int
    test_suite:         list[dict]          # produced by test_generator_node
    final_code:         str                 # produced by boss_round_node
    final_review:       str                 # produced by boss_round_node
    terminated:         bool                # set True when Boss signals done
    termination_reason: str                 # "passed" | "best_effort" | "max_rounds"
    validation_result:  Optional[dict]      # produced by code_validator_node


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _send_task(
    url: str,
    task_id: str,
    session_id: str,
    text: str,
    data: Optional[dict] = None,
    timeout: float = 300.0,
) -> dict:
    """
    Send a task to an agent via A2A /tasks/send and return the raw Task dict.
    Orchestrator uses this ONLY to trigger agents and read back
    orchestration-relevant results (final code, terminated flag).
    It does NOT inspect message content.
    """
    parts = [{"type": "text", "text": text}]
    if data:
        parts.append({"type": "data", "data": data})

    payload = {
        "id": task_id,
        "sessionId": session_id,
        "message": {
            "role": "user",
            "parts": parts,
        },
    }

    token = os.getenv("AGENT_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    headers["X-Sender"] = "Orchestrator"

    async with httpx.AsyncClient() as http:
        resp = await http.post(
            f"{url}/tasks/send",
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()


def _extract_artifact_text(task_dict: dict, artifact_name: str) -> str:
    """Pull text from a named artifact in a Task response dict."""
    for artifact in task_dict.get("artifacts") or []:
        if artifact.get("name") == artifact_name:
            return "\n".join(
                p["text"]
                for p in artifact.get("parts", [])
                if p.get("type") == "text"
            )
    return ""


# ── Node 1: Test Generator ────────────────────────────────────────────────────
# Runs ONCE at start. Generates the test suite for this task.
# LangGraph stores the test suite in state — agents never see this directly.

async def test_generator_node(state: BossWorkerState) -> dict:
    print(f"[Orchestrator] Phase: Test Generator (session={state['session_id']})")

    task_id = f"{state['session_id']}-tests"

    try:
        result = await _send_task(
            url=TEST_GENERATOR_URL,
            task_id=task_id,
            session_id=state["session_id"],
            text=state["task"],
        )
        raw = _extract_artifact_text(result, "test_suite")
        # Test suite comes back as JSON string
        test_suite = json.loads(raw) if raw else []
    except Exception as exc:
        print(f"[Orchestrator] Test Generator failed: {exc} — continuing with empty suite")
        test_suite = []

    print(f"[Orchestrator] Test suite ready: {len(test_suite)} test(s)")
    return {"test_suite": test_suite}


# ── Node 2: Boss Round ─────────────────────────────────────────────────────────
# Triggers the Boss agent to run one full A2A round internally.
# LangGraph only cares about: did it terminate? what is the final code?
# Everything the Boss does internally (plan→code→review) is invisible here.

async def boss_round_node(state: BossWorkerState) -> dict:
    current_round = state["round"] + 1
    print(f"[Orchestrator] Phase: Boss Round {current_round}/{state['max_rounds']}")

    task_id = f"{state['session_id']}-round-{current_round}"

    try:
        result = await _send_task(
            url=BOSS_URL,
            task_id=task_id,
            session_id=state["session_id"],
            text=state["task"],
            # Pass test suite as data so Boss can use it for self-evaluation
            data={"test_suite": state["test_suite"], "round": current_round},
        )

        task_state = result.get("status", {}).get("state", "failed")
        final_code   = _extract_artifact_text(result, "implementation")
        final_review = _extract_artifact_text(result, "review")

        # Boss signals termination via task state and review verdict
        terminated = False
        termination_reason = ""

        if task_state == "completed":
            # Check review verdict to decide if we really need another round
            try:
                raw_review = final_review.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                review_data = json.loads(raw_review)
                verdict = review_data.get("verdict", "fail")
                if verdict == "pass":
                    terminated = True
                    termination_reason = "passed"
                elif current_round >= state["max_rounds"]:
                    terminated = True
                    termination_reason = "best_effort"
            except Exception:
                # Can't parse review — if max rounds, stop
                if current_round >= state["max_rounds"]:
                    terminated = True
                    termination_reason = "max_rounds"

        elif task_state == "failed":
            if current_round >= state["max_rounds"]:
                terminated = True
                termination_reason = "failed"

    except Exception as exc:
        print(f"[Orchestrator] Boss round {current_round} error: {exc}")
        final_code = state.get("final_code", "")
        final_review = state.get("final_review", "")
        terminated = current_round >= state["max_rounds"]
        termination_reason = "error"

    print(f"[Orchestrator] Round {current_round} done — "
          f"terminated={terminated}, reason={termination_reason or 'continuing'}")

    return {
        "round":              current_round,
        "final_code":         final_code   or state.get("final_code", ""),
        "final_review":       final_review or state.get("final_review", ""),
        "terminated":         terminated,
        "termination_reason": termination_reason,
    }


# ── Node 3: Code Validator ────────────────────────────────────────────────────
# Runs ONCE at end. Runs the test suite against the final code.
# Produces the official pass/fail metrics for your thesis.

async def code_validator_node(state: BossWorkerState) -> dict:
    print(f"[Orchestrator] Phase: Code Validator (reason={state['termination_reason']})")

    task_id = f"{state['session_id']}-validate"

    try:
        result = await _send_task(
            url=CODE_VALIDATOR_URL,
            task_id=task_id,
            session_id=state["session_id"],
            text=state["final_code"],
            data={"test_suite": state["test_suite"]},
        )
        raw = _extract_artifact_text(result, "validation_result")
        validation_result = json.loads(raw) if raw else {}
    except Exception as exc:
        print(f"[Orchestrator] Code Validator failed: {exc}")
        validation_result = {"error": str(exc)}

    print(f"[Orchestrator] Validation done: {validation_result}")
    return {"validation_result": validation_result}


# ── Routing logic ─────────────────────────────────────────────────────────────
# This is the ONLY place termination is decided. Clean separation.

def should_continue(state: BossWorkerState) -> str:
    if state["terminated"]:
        return "validate"
    if state["round"] >= state["max_rounds"]:
        return "validate"
    return "continue"


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(BossWorkerState)

    # Register nodes
    graph.add_node("test_generator", test_generator_node)
    graph.add_node("boss_round",     boss_round_node)
    graph.add_node("code_validator", code_validator_node)

    # Entry point
    graph.set_entry_point("test_generator")

    # test_generator always goes to first boss_round
    graph.add_edge("test_generator", "boss_round")

    # After each boss_round: loop back OR go to validator
    graph.add_conditional_edges(
        "boss_round",
        should_continue,
        {
            "continue":  "boss_round",
            "validate":  "code_validator",
        },
    )

    # code_validator always ends
    graph.add_edge("code_validator", END)

    return graph.compile()


# ── Public entry point ──────────────────────────────────────────────────────────────

async def run(task: str, session_id: Optional[str] = None) -> BossWorkerState:
    """
    Run the full Boss-Worker orchestration for a single task.
    Returns the final LangGraph state.
    """
    session_id = session_id or str(uuid.uuid4())[:8]

    initial_state: BossWorkerState = {
        "session_id":         session_id,
        "task":               task,
        "round":              0,
        "max_rounds":         MAX_ROUNDS,
        "test_suite":         [],
        "final_code":         "",
        "final_review":       "",
        "terminated":         False,
        "termination_reason": "",
        "validation_result":  None,
    }

    print(f"\n{'='*60}")
    print(f"[Orchestrator] Starting Boss-Worker session: {session_id}")
    print(f"[Orchestrator] Task: {task[:80]}{'...' if len(task) > 80 else ''}")
    print(f"[Orchestrator] Max rounds: {MAX_ROUNDS}")
    print(f"{'='*60}\n")

    app = build_graph()
    final_state = await app.ainvoke(initial_state)

    print(f"\n{'='*60}")
    print(f"[Orchestrator] Session complete: {session_id}")
    print(f"[Orchestrator] Termination reason: {final_state['termination_reason']}")
    print(f"[Orchestrator] Rounds used: {final_state['round']}/{MAX_ROUNDS}")
    print(f"[Orchestrator] Validation: {final_state['validation_result']}")
    print(f"{'='*60}\n")

    return final_state


# ── CLI entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "Write a Python function that takes a list of integers and returns "
        "the two numbers that add up to a target sum. Handle edge cases."
    )
    asyncio.run(run(task))
