"""
Start all 4 ACP agents concurrently with coloured output.

Usage:
  python3 run_all.py
"""
import subprocess
import sys
import os
import threading

AGENTS = [
    ("BossAgent",     "agents/boss_agent.py",     "\033[95m"),  # magenta
    ("PlannerAgent",  "agents/planner_agent.py",  "\033[94m"),  # blue
    ("CoderAgent",    "agents/coder_agent.py",    "\033[92m"),  # green
    ("ReviewerAgent", "agents/reviewer_agent.py", "\033[93m"),  # yellow
]
RESET = "\033[0m"

BASE = os.path.dirname(__file__)


def stream_output(proc: subprocess.Popen, label: str, colour: str) -> None:
    prefix = f"{colour}[{label}]{RESET} "
    for line in iter(proc.stdout.readline, b""):
        print(prefix + line.decode(errors="replace").rstrip())
    for line in iter(proc.stderr.readline, b""):
        print(prefix + line.decode(errors="replace").rstrip())


procs = []
threads = []

print("Starting ACP agents...")
for name, script, colour in AGENTS:
    path = os.path.join(BASE, script)
    proc = subprocess.Popen(
        [sys.executable, path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=BASE,
    )
    procs.append(proc)
    t = threading.Thread(target=stream_output, args=(proc, name, colour), daemon=True)
    t.start()
    threads.append(t)
    print(f"{colour}[{name}]{RESET} started (pid {proc.pid})")

print("\nAll agents running. Press Ctrl+C to stop.\n")

try:
    for proc in procs:
        proc.wait()
except KeyboardInterrupt:
    print("\nShutting down...")
    for proc in procs:
        proc.terminate()
    for proc in procs:
        proc.wait()
    print("Done.")
