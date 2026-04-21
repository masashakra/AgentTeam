"""
Kaggle Notebook Setup Script for Local Ollama

Run this in a Kaggle notebook cell to:
1. Install Ollama
2. Download Mistral 7B model
3. Start the Ollama server
4. Verify it's working

Usage in Kaggle notebook:
    %pip install -q ollama
    exec(open('/kaggle/input/YOUR_INPUT/kaggle_notebook_setup.py').read())
"""

import subprocess
import time
import sys
import os

def run_cmd(cmd, description="", timeout=300):
    """Run shell command and return success status."""
    print(f"\n{'='*60}")
    print(f"→ {description}")
    print(f"{'='*60}")
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if result.stdout:
            print(result.stdout)
        if result.returncode != 0 and result.stderr:
            print(f"Warning: {result.stderr}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"✗ Command timed out after {timeout}s")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def setup_ollama_kaggle():
    """Main setup for Kaggle notebook."""

    print("\n" + "="*60)
    print("OLLAMA SETUP FOR KAGGLE NOTEBOOK")
    print("="*60)

    # Step 0: Install zstd (required by Ollama)
    print("\n[STEP 0] Installing zstd (required for Ollama)...")
    run_cmd(
        "apt-get update && apt-get install -y zstd",
        "Installing zstd",
        timeout=60
    )

    # Step 1: Install Ollama binary
    print("\n[STEP 1] Installing Ollama...")
    run_cmd(
        "curl -fsSL https://ollama.ai/install.sh | sh",
        "Downloading and installing Ollama",
        timeout=120
    )

    # Step 2: Verify installation
    print("\n[STEP 2] Verifying Ollama installation...")
    run_cmd(
        "which ollama && ollama --version",
        "Checking Ollama installation"
    )

    # Step 3: Start Ollama in background
    print("\n[STEP 3] Starting Ollama server...")
    print("Starting: ollama serve")

    # Start Ollama in background with nohup
    subprocess.Popen(
        "nohup ollama serve > /tmp/ollama.log 2>&1 &",
        shell=True
    )

    # Wait for server to start
    print("Waiting for Ollama server to start (30s)...")
    for i in range(30):
        time.sleep(1)
        try:
            import httpx
            resp = httpx.get("http://localhost:11434/api/tags", timeout=2)
            if resp.status_code == 200:
                print(f"✓ Ollama server is running!")
                break
        except:
            if i % 5 == 0:
                print(f"  Waiting... ({i}s)")
    else:
        print("✗ Ollama server failed to start")
        print("Check logs: cat /tmp/ollama.log")
        return False

    # Step 4: Pull Mistral model
    print("\n[STEP 4] Downloading Mistral 7B model (~4GB)...")
    print("This will take 2-5 minutes...")
    success = run_cmd(
        "ollama pull mistral",
        "Pulling Mistral 7B model",
        timeout=600  # 10 minutes max
    )

    if not success:
        print("✗ Failed to pull model")
        return False

    # Step 5: Verify model is available
    print("\n[STEP 5] Verifying model...")
    run_cmd(
        "ollama list",
        "Listing available models"
    )

    # Step 6: Test inference
    print("\n[STEP 6] Testing inference...")
    test_payload = {
        "model": "mistral",
        "messages": [{"role": "user", "content": "Say hello"}],
        "stream": False
    }

    try:
        import httpx
        print("Sending test request to Ollama...")
        resp = httpx.post(
            "http://localhost:11434/api/chat",
            json=test_payload,
            timeout=60
        )
        result = resp.json()
        content = result.get("message", {}).get("content", "")
        print(f"✓ Test successful!")
        print(f"Response: {content[:100]}")
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False

    # Step 7: Print next steps
    print("\n" + "="*60)
    print("✓ OLLAMA SETUP COMPLETE!")
    print("="*60)
    print("""
NEXT STEPS:

1. Upload AgentTeam repo to Kaggle dataset or git clone it

2. Edit the agent files to use ollama_setup:
   - a2a_system/collab/collab_boss_worker/agents/boss_agent.py
   - a2a_system/collab/collab_boss_worker/agents/planner_agent.py
   - a2a_system/collab/collab_boss_worker/agents/coder_agent.py
   - a2a_system/collab/collab_boss_worker/agents/reviewer_agent.py

   Change:
     from groq_setup.infer import groq_chat, get_tool_call, tool_result_message
   To:
     from ollama_setup.infer import groq_chat, get_tool_call, tool_result_message

3. Install dependencies:
   %pip install -q fastapi uvicorn httpx pydantic

4. Run test:
   %cd a2a_system/collab/collab_boss_worker
   !python3 test_task.py

DEBUGGING:
   - Check Ollama logs: cat /tmp/ollama.log
   - Test Ollama: curl http://localhost:11434/api/tags
   - Restart Ollama: pkill ollama && ollama serve &
""")

    return True


if __name__ == "__main__":
    success = setup_ollama_kaggle()
    sys.exit(0 if success else 1)
