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
    """Switch all agents to use ollama_setup automatically."""
    print("\n" + "="*60)
    print("Switching to OLLAMA (local inference)")
    print("="*60)

    os.environ["LLM_BACKEND"] = "ollama"

    agent_files = [
        "a2a_system/collab/collab_boss_worker/agents/boss_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/planner_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/coder_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/reviewer_agent.py",
    ]

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

            print(f"✓ Updated {filepath.split('/')[-1]}")
        except Exception as e:
            print(f"✗ Failed to update {filepath}: {e}")

    print("\n✓ All agents switched to ollama_setup")
    print("Ready to run: python3 test_task.py\n")


def switch_to_groq():
    """Switch all agents back to groq_setup."""
    print("\n" + "="*60)
    print("Switching to GROQ (cloud API)")
    print("="*60)

    os.environ["LLM_BACKEND"] = "groq"

    agent_files = [
        "a2a_system/collab/collab_boss_worker/agents/boss_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/planner_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/coder_agent.py",
        "a2a_system/collab/collab_boss_worker/agents/reviewer_agent.py",
    ]

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

            print(f"✓ Updated {filepath.split('/')[-1]}")
        except Exception as e:
            print(f"✗ Failed to update {filepath}: {e}")

    print("\n✓ All agents switched to groq_setup")
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
