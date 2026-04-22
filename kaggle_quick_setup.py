"""
kaggle_quick_setup.py — One-click switch between groq and ollama in Kaggle.

Usage in Kaggle notebook:
    exec(open('/kaggle/input/agentteam/kaggle_quick_setup.py').read())

    Then just set:
    switch_to_ollama()  # or switch_to_groq()
"""

import os
import subprocess


def switch_to_ollama():
    """Switch ALL agents to use ollama_setup automatically."""
    print("\n" + "="*60)
    print("Switching to OLLAMA (local inference)")
    print("="*60)

    os.environ["LLM_BACKEND"] = "ollama"

    # Boss-Worker agents (collab_boss_worker) — 8 agents
    agent_files = [
        "a2a_system/collab/collab_boss_worker/agents/boss_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/planner_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/coder_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/reviewer_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/test_generator_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/code_validator_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/comm_logger_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/metrics_tracker_agent.py",
        # Round Table agents (collab_round_table) — 8 agents
        "a2a_system/collab/collab_round_table/agents/architect_agent.py",
        "a2a_system/collab/collab_round_table/agents/coder_agent_rt.py",
        "a2a_system/collab/collab_round_table/agents/debugger_agent.py",
        "a2a_system/collab/collab_round_table/agents/tester_agent.py",
        "a2a_system/collab/collab_round_table/agents/test_generator_agent.py",
        "a2a_system/collab/collab_round_table/agents/code_validator_agent.py",
        "a2a_system/collab/collab_round_table/agents/comm_logger_agent.py",
        "a2a_system/collab/collab_round_table/agents/metrics_tracker_agent.py",
    ]

    updated = 0
    failed = 0

    for filepath in agent_files:
        try:
            with open(filepath, 'r') as f:
                content = f.read()

            # Replace groq_setup with ollama_setup
            new_content = content.replace(
                "from groq_setup.infer import",
                "from ollama_setup.infer import"
            )

            with open(filepath, 'w') as f:
                f.write(new_content)

            print(f"✓ {filepath.split('/')[-1]}")
            updated += 1
        except Exception as e:
            print(f"✗ {filepath.split('/')[-1]}: {e}")
            failed += 1

    print(f"\n✓ Switched {updated} agents to ollama_setup")
    if failed > 0:
        print(f"⚠ {failed} agents failed (may not exist)")
    print("Ready to run: python3 test_task.py\n")


def switch_to_groq():
    """Switch ALL agents back to groq_setup."""
    print("\n" + "="*60)
    print("Switching to GROQ (cloud API)")
    print("="*60)

    os.environ["LLM_BACKEND"] = "groq"

    # Boss-Worker agents (collab_boss_worker) — 8 agents
    agent_files = [
        "a2a_system/collab/collab_boss_worker/agents/boss_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/planner_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/coder_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/reviewer_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/test_generator_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/code_validator_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/comm_logger_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/metrics_tracker_agent.py",
        # Round Table agents (collab_round_table) — 8 agents
        "a2a_system/collab/collab_round_table/agents/architect_agent.py",
        "a2a_system/collab/collab_round_table/agents/coder_agent_rt.py",
        "a2a_system/collab/collab_round_table/agents/debugger_agent.py",
        "a2a_system/collab/collab_round_table/agents/tester_agent.py",
        "a2a_system/collab/collab_round_table/agents/test_generator_agent.py",
        "a2a_system/collab/collab_round_table/agents/code_validator_agent.py",
        "a2a_system/collab/collab_round_table/agents/comm_logger_agent.py",
        "a2a_system/collab/collab_round_table/agents/metrics_tracker_agent.py",
    ]

    updated = 0
    failed = 0

    for filepath in agent_files:
        try:
            with open(filepath, 'r') as f:
                content = f.read()

            # Replace ollama_setup with groq_setup
            new_content = content.replace(
                "from ollama_setup.infer import",
                "from groq_setup.infer import"
            )

            with open(filepath, 'w') as f:
                f.write(new_content)

            print(f"✓ {filepath.split('/')[-1]}")
            updated += 1
        except Exception as e:
            print(f"✗ {filepath.split('/')[-1]}: {e}")
            failed += 1

    print(f"\n✓ Switched {updated} agents to groq_setup")
    if failed > 0:
        print(f"⚠ {failed} agents failed (may not exist)")
    print("Ready to run: python3 test_task.py\n")


def check_status():
    """Check which backend is currently active."""
    print("\n" + "="*60)
    print("Current Status")
    print("="*60)

    filepath = "a2a_system/collab/collab_boss_worker/agents/boss_agent.py"
    try:
        with open(filepath, 'r') as f:
            content = f.read()

        if "from ollama_setup.infer import" in content:
            print("✓ Currently using: OLLAMA (local inference)")
        elif "from groq_setup.infer import" in content:
            print("✓ Currently using: GROQ (cloud API)")
        else:
            print("? Unknown setup")
    except Exception as e:
        print(f"✗ Error checking status: {e}")
