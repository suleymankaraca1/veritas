# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Server

```bash
# Start everything (all 8 agents + Flask API)
.venv/Scripts/python.exe server/app.py

# Test all external API connections (Featherless, AIML, Tavily, Band)
.venv/Scripts/python.exe test_apis.py

# Clear stale Band message backlog before a fresh run
.venv/Scripts/python.exe clear_backlog.py
```

Server logs go to `server_out.log` (stdout) and `server_err.log` (stderr) when started via PowerShell redirect. The `/api/health` endpoint confirms the server is up.

## Architecture

VERITAS is an 8-agent fact-checking pipeline running on the [Band SDK](https://app.band.ai). All agents connect to a single shared Band chat room (`BAND_CHAT_ROOM_ID`) and communicate exclusively through Band messages (no direct in-process calls between agents). The Flask server is the only entry point.

### Request Flow

```
POST /api/analyze
  └─ gateway.analyze()          # creates TASK_ID, blocks on threading.Event
       └─ REST → Orchestrator   # "Please analyze... TASK_ID: <id>"
            └─ gpt-4o-mini      # extracts factual claims → "Claim 1: ..."
                 └─ REST → ResearcherMaster  # "CLAIMS:\n1|claim\n2|claim..."
                      ├─ round-robin dispatch → ResearcherB, C, D via REST
                      └─ own share → Tavily (5 results) + gpt-4o-mini → SourceValidator
                           └─ ResearcherB/C → Tavily (5) + gpt-4o-mini → SourceValidator
                                └─ ResearcherD → Tavily academic domains + gpt-4o-mini → SourceValidator
                                     └─ SourceValidator (waits for all 4)
                                          └─ gpt-4o-mini consensus analysis
                                               └─ REST → Reporter
                                                    └─ Featherless/Gemma → plain-text report
                                                         └─ REST → Orchestrator → Gateway
                                                              └─ threading.Event.set() → response
```

### Agent Protocol (inter-agent message format)

All messages are structured plain text with uppercase keyword lines:

- **Gateway → Orchestrator**: `TASK_ID: <id>\n\nPlease analyze...`
- **Orchestrator → ResearcherMaster**: `TASK_ID: <id>\nCLAIMS:\n1|<claim>\n2|<claim>`
- **ResearcherMaster → B/C/D**: `TASK_ID: <id>\nRESEARCHER: <id>\nCLAIMS:\n1|<claim>`
- **Researchers → SourceValidator**: `TASK_ID: <id>\nRESEARCHER: <id>\nBULGULAR:\n<findings>`
- **SourceValidator → Reporter**: `TASK_ID: <id>\nDogrulanmis bulgular...\n=== KAYNAK DOGRULAMA ===`
- **Reporter → Orchestrator**: `TASK_ID: <id>\nFINAL_REPORT\n\n<plain text report>`
- **Orchestrator → Gateway**: same FINAL_REPORT forwarded, Gateway tag added

Each agent's `on_message` filters by checking for its own handle name in the message content (e.g. `"orchestrator" in content_lower`), `"task_id:"`, and a domain-specific keyword.

### Critical Band SDK Behavior

`is_session_bootstrap=True` is set on **every agent's first message per session**, not just history replay. The fix applied to all agents:

```python
if is_session_bootstrap and len(history) > 0:
    return  # skip only when real old history exists
```

Without `len(history) > 0`, the first real request is silently dropped.

### LLM Usage per Agent

| Agent | Model | Purpose |
|---|---|---|
| Orchestrator | gpt-4o-mini (AIML) | Extract factual claims from input text |
| ResearcherMaster | Tavily + gpt-4o-mini | Web search + claim analysis (own share) |
| ResearcherB | Tavily + gpt-4o-mini | Web search + claim analysis |
| ResearcherC | Tavily + gpt-4o-mini | Web search + claim analysis |
| ResearcherD | Tavily academic domains + gpt-4o-mini | Academic source search (pubmed, arxiv, dergipark, etc.) with general fallback |
| SourceValidator | gpt-4o-mini (AIML) | Consensus analysis across all 4 researcher findings |
| Reporter | Featherless/Gemma 4 26B | Final plain-text report generation |
| Gateway | — | Bridge between Flask and Band; no LLM |

### API Response Format

`POST /api/analyze` returns:

```json
{
  "task_id": "abc12345",
  "report": {
    "text": "TASK_ID: ...\n\nCLAIMS:\n1. ...\n\nAVERAGE SCORE: 85/100\n\nRESULTS:\n..."
  },
  "raw": "<full Band message including mentions>"
}
```

`report.text` is the plain-text report extracted after the `FINAL_REPORT` line. If the reporter outputs JSON (legacy), `report` is the parsed JSON object instead.

## Environment Setup

Copy `.env.example` to `.env`. Each of the 8 agents needs its own `*_AGENT_ID` and `*_API_KEY` from the Band dashboard. The `BAND_CHAT_ROOM_ID` must be a fresh room when changing agents to avoid bootstrap issues.

**File encoding**: Always write Python files with UTF-8 no-BOM encoding. Never use PowerShell `Get-Content`/`Set-Content` on these files — it corrupts non-ASCII characters. Use Python's `open(..., encoding='utf-8')` or the Write tool instead.
