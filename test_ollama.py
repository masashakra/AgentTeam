#!/usr/bin/env python3
"""
Quick test to verify Ollama is working before running the full system.

Usage:
    python3 test_ollama.py

Output:
    - Tests Ollama connectivity
    - Tests basic inference
    - Reports model and performance
"""
import time
import httpx

OLLAMA_API = "http://localhost:11434/api/chat"


def test_ollama():
    print("Testing Ollama setup...\n")

    # Test 1: Check connectivity
    print("[1] Checking Ollama connectivity...")
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=5)
        models = resp.json().get("models", [])
        print(f"    ✓ Ollama is running")
        print(f"    Available models: {[m['name'] for m in models]}")
    except Exception as e:
        print(f"    ✗ Ollama not running: {e}")
        print("    Start Ollama with: ollama serve")
        return False

    # Test 2: Test inference
    print("\n[2] Testing basic inference...")
    payload = {
        "model": "mistral",
        "messages": [{"role": "user", "content": "Say 'hello world' and nothing else."}],
        "stream": False,
    }

    try:
        start = time.time()
        resp = httpx.post(OLLAMA_API, json=payload, timeout=60)
        elapsed = time.time() - start
        msg = resp.json()["message"]["content"]
        print(f"    ✓ Inference successful ({elapsed:.1f}s)")
        print(f"    Response: {msg[:60]}")
    except Exception as e:
        print(f"    ✗ Inference failed: {e}")
        return False

    # Test 3: Test with tools (check if response parses)
    print("\n[3] Testing tool-format response...")
    payload = {
        "model": "mistral",
        "messages": [
            {"role": "user", "content": "Write a Python function to add two numbers."}
        ],
        "stream": False,
    }

    try:
        start = time.time()
        resp = httpx.post(OLLAMA_API, json=payload, timeout=60)
        elapsed = time.time() - start
        msg = resp.json()["message"]["content"]
        print(f"    ✓ Code generation working ({elapsed:.1f}s)")
        print(f"    Sample output (first 100 chars):\n    {msg[:100]}")
    except Exception as e:
        print(f"    ✗ Code generation failed: {e}")
        return False

    print("\n" + "=" * 60)
    print("✓ Ollama setup verified and ready!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Edit agents to use: from ollama_setup.infer import ...")
    print("2. Run: cd a2a_system/collab/collab_boss_worker && python3 test_task.py")
    return True


if __name__ == "__main__":
    success = test_ollama()
    exit(0 if success else 1)
