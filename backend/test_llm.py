"""Quick LLM connectivity test."""
import asyncio
import os
import time
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load env like main.py does
from pathlib import Path
from dotenv import load_dotenv
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()

from app.core.llm_client import chat as llm_chat


async def main():
    print(f"Model: {os.getenv('LLM_MODEL')}")
    print(f"Base URL: {os.getenv('LLM_BASE_URL')}")
    print(f"API Key: {os.getenv('LLM_API_KEY', '')[:15]}...")
    
    print("\nSending simple test request...")
    start = time.time()
    try:
        resp = await llm_chat(
            system="You are a helpful assistant. Reply in JSON.",
            messages=[{"role": "user", "content": "Say hello in JSON: {\"greeting\": \"...\"}"}],
            model=None,
        )
        elapsed = time.time() - start
        print(f"✅ Response in {elapsed:.1f}s:")
        print(f"  Content: {resp.content[:200]}")
        print(f"  Stop reason: {resp.stop_reason}")
    except Exception as e:
        elapsed = time.time() - start
        print(f"❌ Error after {elapsed:.1f}s: {type(e).__name__}: {e}")


asyncio.run(main())
