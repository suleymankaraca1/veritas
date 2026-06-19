"""
Marks all pending old messages in the Band room as processed on behalf of each agent.
Clears accumulated backlog so new requests are handled immediately.
"""
import os, requests, time
from dotenv import load_dotenv

load_dotenv()

ROOM    = os.getenv("BAND_CHAT_ROOM_ID")
BASE    = "https://app.band.ai/api/v1/agent/chats"

AGENTS  = {
    "Gateway":          os.getenv("GATEWAY_API_KEY"),
    "Orchestrator":     os.getenv("ORCHESTRATOR_API_KEY"),
    "ResearcherMaster": os.getenv("RESEARCHER_MASTER_API_KEY"),
    "ResearcherB":      os.getenv("RESEARCHER_B_API_KEY"),
    "ResearcherC":      os.getenv("RESEARCHER_C_API_KEY"),
    "ResearcherD":      os.getenv("RESEARCHER_D_API_KEY"),
    "SourceValidator":  os.getenv("SOURCE_VALIDATOR_API_KEY"),
    "Reporter":         os.getenv("REPORTER_API_KEY"),
}


def get_next_message(api_key):
    """Returns the next unprocessed message for this agent."""
    r = requests.get(
        f"{BASE}/{ROOM}/messages/next",
        headers={"X-API-Key": api_key},
        timeout=10,
    )
    if r.status_code == 200:
        return r.json().get("data", {}).get("id")
    return None


def claim_and_skip(api_key, msg_id):
    """Claims a message, then marks it as processed without running the LLM."""
    # First: set to processing
    r1 = requests.post(
        f"{BASE}/{ROOM}/messages/{msg_id}/processing",
        headers={"X-API-Key": api_key},
        timeout=10,
    )
    if r1.status_code in (200, 201):
        # Then: set to processed
        r2 = requests.post(
            f"{BASE}/{ROOM}/messages/{msg_id}/processed",
            headers={"X-API-Key": api_key},
            timeout=10,
        )
        return r2.status_code in (200, 201)
    return False


def clear_agent_backlog(name, api_key, max_msgs=2000):
    print(f"\n[{name}] Clearing backlog...")
    count = 0
    while count < max_msgs:
        msg_id = get_next_message(api_key)
        if msg_id is None:
            print(f"  [{name}] Queue clear ({count} messages cleared)")
            break
        ok = claim_and_skip(api_key, msg_id)
        if ok:
            count += 1
            if count % 50 == 0:
                print(f"  [{name}] {count} messages cleared...")
        else:
            print(f"  [{name}] Could not claim message {msg_id}, stopping")
            break
    return count


if __name__ == "__main__":
    print("VERITAS Band Backlog Cleaner")
    print(f"Room: {ROOM}")
    total = 0
    for name, key in AGENTS.items():
        cleared = clear_agent_backlog(name, key)
        total += cleared
    print(f"\nTotal {total} messages cleared.")
    print("You can now restart the server.")
