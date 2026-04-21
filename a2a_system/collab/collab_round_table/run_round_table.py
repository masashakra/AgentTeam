"""
run_round_table.py — starts the registry, all 8 Round Table agents, and runs the LangGraph orchestrator.

Usage:
  cd collab_round_table
  python3 run_round_table.py
  python3 run_round_table.py "Your custom task here"

Ports:
  8099 AgentRegistry   (shared, at project root)
  8010 ArchitectAgent
  8011 CoderAgentRT
  8012 DebuggerAgent
  8013 TesterAgent
  8014 TestGeneratorAgent
  8015 CodeValidatorAgent
  8016 CommunicationLoggerAgent
  8017 MetricsTrackerAgent
"""
from __future__ import annotations

import asyncio
import json
import signal
import sys
import textwrap
from pathlib import Path

import httpx

ROOT = Path(__file__).parent
PROJECT_ROOT = ROOT.parent.parent.parent   # AgentTeam/

REGISTRY_PORT = 8099

AGENTS = [
    ("ArchitectAgent",         8010, "agents.architect_agent:app"),
    ("CoderAgentRT",           8011, "agents.coder_agent_rt:app"),
    ("DebuggerAgent",          8012, "agents.debugger_agent:app"),
    ("TesterAgent",            8013, "agents.tester_agent:app"),
    ("TestGeneratorAgent",     8014, "agents.test_generator_agent:app"),
    ("CodeValidatorAgent",     8015, "agents.code_validator_agent:app"),
    ("CommLoggerAgent",        8016, "agents.comm_logger_agent:app"),
    ("MetricsTrackerAgent",    8017, "agents.metrics_tracker_agent:app"),
]

COLORS = {
    "Registry":            "\033[37m",   # white
    "ArchitectAgent":      "\033[94m",   # blue
    "CoderAgentRT":        "\033[92m",   # green
    "DebuggerAgent":       "\033[91m",   # red
    "TesterAgent":         "\033[93m",   # yellow
    "TestGeneratorAgent":  "\033[96m",   # cyan
    "CodeValidatorAgent":  "\033[97m",   # bright white
    "CommLoggerAgent":     "\033[35m",   # magenta
    "MetricsTrackerAgent": "\033[90m",   # dark gray
}
RESET = "\033[0m"

DEFAULT_TASK = (
    "Write a Python function that finds the longest common subsequence "
    "of two strings"
)


async def stream_output(name: str, stream: asyncio.StreamReader) -> None:
    color = COLORS.get(name, "")
    while True:
        line = await stream.readline()
        if not line:
            break
        print(f"{color}[{name}]{RESET} {line.decode(errors='replace').rstrip()}", flush=True)


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
        cwd=str(PROJECT_ROOT),
        env={**__import__("os").environ, "PYTHONPATH": f"{PROJECT_ROOT}:{ROOT}"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    asyncio.ensure_future(stream_output(name, proc.stdout))
    return proc


async def wait_for_ports(ports: list[int], timeout: float = 60.0) -> None:
    """Poll /.well-known/agent.json on each port until all respond."""
    deadline = asyncio.get_event_loop().time() + timeout
    pending = set(ports)
    async with httpx.AsyncClient() as client:
        while pending:
            if asyncio.get_event_loop().time() > deadline:
                raise RuntimeError(f"Services on ports {pending} did not start within {timeout}s")
            await asyncio.sleep(1.0)
            for port in list(pending):
                try:
                    resp = await client.get(
                        f"http://localhost:{port}/.well-known/agent.json",
                        timeout=2.0,
                    )
                    if resp.status_code == 200:
                        pending.discard(port)
                except Exception:
                    pass


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


def _banner(title: str) -> None:
    width = 70
    print("\n" + "─" * width)
    print(f"  {title}")
    print("─" * width)


def _print_result(final_state: dict) -> None:
    agent_outputs = final_state.get("agent_outputs", {})
    session_id = final_state.get("session_id", "?")
    reason = final_state.get("termination_reason", "?")
    total_rounds = final_state.get("round", 1) - 1

    _banner("Round Table Results")
    print(f"  Session ID         : {session_id}")
    print(f"  Termination reason : {reason}")
    print(f"  Total rounds       : {total_rounds}")
    print(f"  Final pass rate    : {agent_outputs.get('final_pass_rate', '?')}")

    _banner("Final Code (CoderAgentRT)")
    code = agent_outputs.get("Coder", "# No code generated")
    print(textwrap.indent(code, "  "))

    _banner("Architect Design")
    print(textwrap.indent(agent_outputs.get("Architect", "(none)"), "  "))

    _banner("Debugger Analysis")
    print(textwrap.indent(agent_outputs.get("Debugger", "(none)"), "  "))

    _banner("Tester Feedback")
    print(textwrap.indent(agent_outputs.get("Tester", "(none)"), "  "))

    _banner("Validation Report")
    report_raw = agent_outputs.get("validation_report", "{}")
    try:
        report = json.loads(report_raw)
        print(textwrap.indent(json.dumps(report, indent=2), "  "))
    except Exception:
        print(textwrap.indent(report_raw, "  "))

    print()
    print(f"  Logs: collab_round_table/logs/  (session_id={session_id})")
    print("─" * 70 + "\n")


async def main(task: str) -> None:
    procs = []

    # ── Start registry first ──────────────────────────────────────────────────
    print(f"\n{COLORS['Registry']}[Registry]{RESET} Starting on port {REGISTRY_PORT} …")
    registry_proc = await run_registry()
    procs.append(registry_proc)
    try:
        await wait_for_registry(timeout=30.0)
        print(f"{COLORS['Registry']}[Registry]{RESET} Ready.")
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        registry_proc.terminate()
        return

    # ── Start agents ──────────────────────────────────────────────────────────
    print(f"\nStarting Round Table agents …\n")
    for name, port, app in AGENTS:
        p = await run_agent(name, port, app)
        procs.append(p)
        print(f"  {COLORS.get(name, '')}[{name}]{RESET} started on port {port} (pid {p.pid})")

    print(f"\nWaiting for all agents to be ready …")
    ports = [port for _, port, _ in AGENTS]
    try:
        await wait_for_ports(ports, timeout=60.0)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        for p in procs:
            p.terminate()
        return

    print(f"All agents ready.\n")

    # ── Run the LangGraph orchestrator ────────────────────────────────────────
    from orchestrator import run as run_orchestrator

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _shutdown(*_):
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    try:
        final_state = await run_orchestrator(task, max_rounds=4)
        _print_result(final_state)
    except Exception as exc:
        print(f"\nOrchestrator error: {exc}")
        import traceback
        traceback.print_exc()
    finally:
        print("\nShutting down agents …")
        for p in procs:
            try:
                p.terminate()
            except ProcessLookupError:
                pass
        await asyncio.gather(*(p.wait() for p in procs), return_exceptions=True)
        print("All agents stopped.")


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else DEFAULT_TASK
    asyncio.run(main(task))
