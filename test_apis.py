"""
Quick API health check — tests Featherless, AIML, Tavily, and Band in sequence.
Usage: python test_apis.py
"""
import os, json, time
import requests
from dotenv import load_dotenv

load_dotenv()

FEATHERLESS_KEY   = os.getenv("FEATHERLESS_API_KEY")
FEATHERLESS_BASE  = os.getenv("FEATHERLESS_API_BASE", "https://api.featherless.ai/v1")
FEATHERLESS_MODEL = os.getenv("FEATHERLESS_MODEL", "google/gemma-4-26b-a4b-it")

AIML_KEY   = os.getenv("AIML_API_KEY")
AIML_BASE  = os.getenv("AIML_API_BASE", "https://api.aimlapi.com/v1")
AIML_MODEL = os.getenv("AIML_MODEL", "openai/gpt-oss-120b")

TAVILY_KEY = os.getenv("TAVILY_API_KEY")

GATEWAY_KEY = os.getenv("GATEWAY_API_KEY")
ROOM_ID     = os.getenv("BAND_CHAT_ROOM_ID")
ORCH_ID     = os.getenv("ORCHESTRATOR_AGENT_ID")
ORCH_HANDLE = os.getenv("ORCHESTRATOR_HANDLE", "@suleymankaracakod/orchestrator")


def test_chat(label, base_url, api_key, model, prompt="Hello, what is 1+1? Reply with the number only."):
    print(f"\n{'='*60}")
    print(f"TEST: {label} ({model})")
    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 20,
        "temperature": 0,
    }
    t0 = time.time()
    try:
        r = requests.post(url, headers=headers, json=body, timeout=30)
        elapsed = time.time() - t0
        print(f"  Status   : {r.status_code}")
        if r.status_code == 200:
            resp = r.json()
            text = resp["choices"][0]["message"]["content"]
            print(f"  Response : {text.strip()}")
            print(f"  Time     : {elapsed:.1f}s  ✓ OK")
        else:
            print(f"  Error    : {r.text[:300]}")
            print(f"  ✗ FAILED")
    except Exception as e:
        print(f"  Exception: {e}  ✗ FAILED")


def test_tavily():
    print(f"\n{'='*60}")
    print("TEST: Tavily Search")
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=TAVILY_KEY)
        result = client.search("Turkey population 2024", max_results=2)
        print(f"  Result count : {len(result.get('results', []))}")
        if result.get("results"):
            print(f"  First title  : {result['results'][0].get('title','?')[:60]}")
        print("  ✓ OK")
    except Exception as e:
        print(f"  Exception: {e}  ✗ FAILED")


def test_band_send():
    print(f"\n{'='*60}")
    print("TEST: Band REST — send message (Gateway API key)")
    url = f"https://app.band.ai/api/v1/agent/chats/{ROOM_ID}/messages"
    headers = {
        "Authorization": f"Bearer {GATEWAY_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "content": f"{ORCH_HANDLE}\n\nTASK_ID: test-debug\n\nThis is a debug message. Please ignore.",
        "mentions": [{"id": ORCH_ID}],
    }
    try:
        r = requests.post(url, headers=headers, json=body, timeout=15)
        print(f"  Status   : {r.status_code}")
        if r.status_code in (200, 201):
            print(f"  Response : {r.text[:200]}")
            print("  ✓ OK")
        else:
            print(f"  Error    : {r.text[:300]}")
            print("  ✗ FAILED")
    except Exception as e:
        print(f"  Exception: {e}  ✗ FAILED")


def list_featherless_models():
    """Lists available Gemma models on Featherless."""
    print(f"\n{'='*60}")
    print("TEST: Featherless model list (gemma filter)")
    url = f"{FEATHERLESS_BASE}/models"
    headers = {"Authorization": f"Bearer {FEATHERLESS_KEY}"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            models = r.json().get("data", [])
            gemma = [m["id"] for m in models if "gemma" in m["id"].lower()]
            print(f"  Total models : {len(models)}")
            print(f"  Gemma models ({len(gemma)}):")
            for m in gemma[:15]:
                marker = " ← IN USE" if m == FEATHERLESS_MODEL else ""
                print(f"    {m}{marker}")
        else:
            print(f"  Error: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"  Exception: {e}")


if __name__ == "__main__":
    print("VERITAS API Diagnostics — Starting...")
    list_featherless_models()
    test_chat("Featherless / Gemma", FEATHERLESS_BASE, FEATHERLESS_KEY, FEATHERLESS_MODEL)
    test_chat("AIML API / GPT-OSS-120B", AIML_BASE, AIML_KEY, AIML_MODEL)
    test_tavily()
    test_band_send()
    print(f"\n{'='*60}")
    print("Diagnostics complete.")
