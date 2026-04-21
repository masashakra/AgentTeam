"""
infer_wrapper.py — Single import that switches between groq_setup and ollama_setup.

Usage:
    from infer_wrapper import groq_chat, get_tool_call, tool_result_message

    Automatically uses:
    - ollama_setup if LLM_BACKEND=ollama
    - groq_setup if LLM_BACKEND=groq (default)

No manual editing of 4 files needed!
"""
import os

LLM_BACKEND = os.getenv("LLM_BACKEND", "groq").lower()

if LLM_BACKEND == "ollama":
    from ollama_setup.infer import groq_chat, groq_complete, generate, get_tool_call, tool_result_message
    print("[infer_wrapper] Using ollama_setup (local inference)")
elif LLM_BACKEND == "groq":
    from groq_setup.infer import groq_chat, groq_complete, generate, get_tool_call, tool_result_message
    print("[infer_wrapper] Using groq_setup (cloud API)")
else:
    raise ValueError(f"Unknown LLM_BACKEND: {LLM_BACKEND}. Use 'groq' or 'ollama'")

__all__ = ["groq_chat", "groq_complete", "generate", "get_tool_call", "tool_result_message"]
