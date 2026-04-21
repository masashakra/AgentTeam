"""
run_all.py — starts the registry and all agents, runs the orchestrator, tails output.
Press Ctrl+C to stop everything.

Ports:
  8099 AgentRegistry      (shared, at project root)
  8000 BossAgent
  8001 PlannerAgent
  8002 CoderAgent
  8003 ReviewerAgent
  8004 TestGeneratorAgent
  8005 CodeValidatorAgent
  8006 CommLoggerAgent
  8007 MetricsTrackerAgent
"""
from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).parent
PROJECT_ROOT = ROOT.parent.parent.parent   # AgentTeam/

# Add ROOT to path so orchestrator can be imported
sys.path.insert(0, str(ROOT))

REGISTRY_PORT = 8099

# ── Agent warm-up wait (seconds after boot before orchestrator runs) ──────────
AGENT_WARMUP = 3.0

AGENTS = [
    ("BossAgent",           8000, "agents.boss_agent:app"),
    ("PlannerAgent",        8001, "agents.planner_agent:app"),
    ("CoderAgent",          8002, "agents.coder_agent:app"),
    ("ReviewerAgent",       8003, "agents.reviewer_agent:app"),
    ("TestGeneratorAgent",  8004, "agents.test_generator_agent:app"),
    ("CodeValidatorAgent",  8005, "agents.code_validator_agent:app"),
    ("CommLoggerAgent",     8006, "agents.comm_logger_agent:app"),
    ("MetricsTrackerAgent", 8007, "agents.metrics_tracker_agent:app"),
]

COLORS = {
    "Registry":           "\033[37m",   # white
    "BossAgent":          "\033[95m",   # magenta
    "PlannerAgent":       "\033[94m",   # blue
    "CoderAgent":         "\033[92m",   # green
    "ReviewerAgent":      "\033[93m",   # yellow
    "TestGeneratorAgent": "\033[96m",   # cyan
    "CodeValidatorAgent": "\033[91m",   # red
    "CommLoggerAgent":    "\033[90m",   # dark gray
    "MetricsTrackerAgent": "\033[95m",  # magenta (reuse or choose another)
    "Orchestrator":       "\033[1;37m", # bold white
}
RESET = "\033[0m"

# ── Task to run ───────────────────────────────────────────────────────────────
# Replace this with your benchmark runner later
DEFAULT_TASK = (
    "Write a Python function that takes a list of integers and a target integer, "
    "and returns the indices of the two numbers that add up to the target. "
    "Handle edge cases: empty list, no solution, duplicate values."
)


# ── Subprocess helpers ────────────────────────────────────────────────────────

async def stream_output(name: str, stream: asyncio.StreamReader) -> None:
    color = COLORS.get(name, "")
    while True:
        line = await stream.readline()
        if not line:
            break
        print(f"{color}[{name}]{RESET} {line.decode(errors='replace').rstrip()}")


async def run_registry() -> asyncio.subprocess.Process:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(PROJECT_ROOT / "registry.py"),
        cwd=str(PROJECT_ROOT),
        env={**__import__("os").environ},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    asyncio.ensure_future(stream_output("Registry", proc.stdout))
    return proc


async def run_agent(name: str, port: int, app: str) -> asyncio.subprocess.Process:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "uvicorn", app,
        "--host", "0.0.0.0",
        "--port", str(port),
        "--no-access-log",
        cwd=str(ROOT),
        env={
            **__import__("os").environ,
            "PYTHONPATH": ":".join([str(PROJECT_ROOT), str(ROOT)]),
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    asyncio.ensure_future(stream_output(name, proc.stdout))
    return proc


# ── Registry readiness check ──────────────────────────────────────────────────

async def wait_for_registry(timeout: float = 30.0) -> None:
    """Wait for registry to respond on its well-known endpoint."""
    deadline = asyncio.get_event_loop().time() + timeout
    async with httpx.AsyncClient() as client:
        while True:
            if asyncio.get_event_loop().time() > deadline:
                raise RuntimeError(f"Registry did not start within {timeout}s")
            await asyncio.sleep(0.5)
            try:
                resp = await client.get(
                    f"http://localhost:{REGISTRY_PORT}/.well-known/agent-registry.json",
                    timeout=2.0,
                )
                if resp.status_code == 200:
                    return
            except Exception:
                pass


async def wait_for_agent(name: str, port: int, timeout: float = 30.0) -> None:
    """Wait for a single agent to serve its agent card."""
    deadline = asyncio.get_event_loop().time() + timeout
    async with httpx.AsyncClient() as client:
        while True:
            if asyncio.get_event_loop().time() > deadline:
                raise RuntimeError(f"{name} did not start within {timeout}s")
            await asyncio.sleep(0.5)
            try:
                resp = await client.get(
                    f"http://localhost:{port}/.well-known/agent.json",
                    timeout=2.0,
                )
                if resp.status_code == 200:
                    return
            except Exception:
                pass


async def wait_for_all_agents(timeout: float = 30.0) -> None:
    """Wait for every agent to be reachable before orchestrator starts."""
    await asyncio.gather(*[
        wait_for_agent(name, port, timeout)
        for name, port, _ in AGENTS
    ])


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    procs = []
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()

    def _shutdown(*_):
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    # ── Phase 1: Start registry ───────────────────────────────────────────────
    print(f"{COLORS['Registry']}[Registry]{RESET} Starting on port {REGISTRY_PORT} …")
    registry_proc = await run_registry()
    procs.append(registry_proc)
    try:
        await wait_for_registry(timeout=30.0)
        print(f"{COLORS['Registry']}[Registry]{RESET} Ready.\n")
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        registry_proc.terminate()
        return

    # ── Phase 2: Start all agents ─────────────────────────────────────────────
    print("Starting all agents …\n")
    for name, port, app in AGENTS:
        p = await run_agent(name, port, app)
        procs.append(p)
        print(f"  {COLORS.get(name, '')}[{name}]{RESET} started on port {port} (pid {p.pid})")

    # Wait until every agent is actually serving (not just started)
    print("\nWaiting for all agents to be ready …")
    try:
        await wait_for_all_agents(timeout=30.0)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        for p in procs:
            p.terminate()
        return

    print(f"\nAll agents ready. Waiting {AGENT_WARMUP}s for registry sync …\n")
    await asyncio.sleep(AGENT_WARMUP)

    # ── Phase 3: Run orchestrator ─────────────────────────────────────────────
    # Import here so orchestrator.py is only loaded after agents are up
    from orchestrator import run as orchestrate

    orch_color = COLORS["Orchestrator"]
    print(f"{orch_color}[Orchestrator]{RESET} Starting Boss-Worker session …\n")

    orchestrator_task = asyncio.create_task(
        _run_orchestrator(orchestrate, stop_event)
    )

    # ── Phase 4: Wait for orchestrator to finish OR Ctrl+C ────────────────────
    done, _ = await asyncio.wait(
        [orchestrator_task, asyncio.create_task(stop_event.wait())],
        return_when=asyncio.FIRST_COMPLETED,
    )

    # ── Phase 5: Shutdown ─────────────────────────────────────────────────────
    if not orchestrator_task.done():
        orchestrator_task.cancel()

    print("\nShutting down …")
    for p in procs:
        p.terminate()
    await asyncio.gather(*(p.wait() for p in procs), return_exceptions=True)
    print("All agents stopped.")


async def _run_orchestrator(orchestrate, stop_event: asyncio.Event) -> None:
    """Run the orchestrator and signal stop when done."""
    orch_color = COLORS["Orchestrator"]
    try:
        final_state = await orchestrate(task=DEFAULT_TASK)

        print(f"\n{orch_color}[Orchestrator]{RESET} ── Final Result ──────────────────────")
        print(f"{orch_color}[Orchestrator]{RESET} Termination : {final_state['termination_reason']}")
        print(f"{orch_color}[Orchestrator]{RESET} Rounds used : {final_state['round']}/{final_state['max_rounds']}")
        print(f"{orch_color}[Orchestrator]{RESET} Validation  : {final_state['validation_result']}")
        print(f"{orch_color}[Orchestrator]{RESET} ─────────────────────────────────────\n")

        if final_state.get("final_code"):
            print(f"{orch_color}[Orchestrator]{RESET} Final code:\n")
            print(final_state["final_code"])

    except Exception as exc:
        print(f"{orch_color}[Orchestrator]{RESET} ERROR: {exc}")

    finally:
        # Orchestrator finished — signal main to shut down agents
        stop_event.set()


if __name__ == "__main__":
    asyncio.run(main())