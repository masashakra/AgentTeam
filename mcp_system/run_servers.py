"""
run_servers.py — Start all three MCP worker servers concurrently with colored output.
Usage: python3.12 run_servers.py
"""
import subprocess
import sys
import threading
import os

SERVERS = [
    {"name": "PlannerAgent", "module": "servers.planner_server",  "port": 8101, "color": "\033[36m"},  # cyan
    {"name": "CoderAgent",   "module": "servers.coder_server",    "port": 8102, "color": "\033[32m"},  # green
    {"name": "ReviewerAgent","module": "servers.reviewer_server", "port": 8103, "color": "\033[35m"},  # magenta
]
RESET = "\033[0m"


def stream_output(proc: subprocess.Popen, label: str, color: str) -> None:
    prefix = f"{color}[{label}]{RESET} "
    for line in iter(proc.stdout.readline, b""):
        print(prefix + line.decode(errors="replace").rstrip())
    for line in iter(proc.stderr.readline, b""):
        print(prefix + line.decode(errors="replace").rstrip())


def main() -> None:
    procs = []
    threads = []
    cwd = os.path.dirname(os.path.abspath(__file__))

    for srv in SERVERS:
        print(f"{srv['color']}[{srv['name']}]{RESET} Starting on port {srv['port']}...")
        proc = subprocess.Popen(
            [sys.executable, "-m", srv["module"]],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
        )
        procs.append(proc)
        t = threading.Thread(
            target=stream_output,
            args=(proc, srv["name"], srv["color"]),
            daemon=True,
        )
        t.start()
        threads.append(t)

    print("\n\033[1mAll MCP servers started. Press Ctrl+C to stop.\033[0m\n")

    try:
        for proc in procs:
            proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down servers...")
        for proc in procs:
            proc.terminate()


if __name__ == "__main__":
    main()
