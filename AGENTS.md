# VERITAS — Agent Pipeline

VERITAS runs 8 agents on the Band SDK. All agents share a single Band chat room and communicate exclusively through messages — there are no direct function calls between agents at runtime.

---

## Pipeline Overview

```
User Input (Flask)
    │
    ▼
┌─────────────┐
│   Gateway   │  Creates TASK_ID, blocks on threading.Event
└──────┬──────┘
       │ REST message → Band chat room
       ▼
┌──────────────────┐
│   Orchestrator   │  Extracts factual claims from input (GPT-4o-mini)
└────────┬─────────┘
         │ CLAIMS: 1|claim\n2|claim...
         ▼
┌──────────────────────┐
│  Researcher Master   │  Splits claims, dispatches to B/C/D, keeps own share
└──┬────────┬────┬─────┘
   │        │    │
   ▼        ▼    ▼
  [B]      [C]  [D]      Each researcher: Tavily search + GPT-4o-mini analysis
   │        │    │        ResearcherD uses academic domains (arXiv, PubMed, etc.)
   └────────┴────┘
         │ BULGULAR (findings)
         ▼
┌────────────────────┐
│  Source Validator  │  Waits for all 4 researchers, runs consensus analysis (GPT-4o-mini)
└────────┬───────────┘
         │ Validated findings
         ▼
┌──────────────┐
│   Reporter   │  Generates final plain-text report (Gemma 4 26B / Featherless)
└──────┬───────┘
       │ FINAL_REPORT
       ▼
┌──────────────────┐
│   Orchestrator   │  Forwards report to Gateway
└────────┬─────────┘
         │
         ▼
┌─────────────┐
│   Gateway   │  threading.Event.set() → Flask returns response
└─────────────┘
```

---

## Agent Reference

### Gateway

**Role:** Bridge between Flask and the Band chat room.

- Receives the user's text from Flask via `gateway.analyze(text)`
- Creates a unique `TASK_ID` (UUID4)
- Posts a message to the Band room: `TASK_ID: <id>\n\nPlease analyze...`
- Blocks the Flask request thread on a `threading.Event` (timeout: 900s)
- When it receives the final report back from Orchestrator, calls `Event.set()` and returns the result to Flask
- **No LLM** — pure message routing

---

### Orchestrator

**Role:** Claim extraction and pipeline coordination.

- Listens for messages containing `"task_id:"` and `"please analyze"`
- Calls GPT-4o-mini (AIML API) to extract verifiable factual claims from the input text
- Formats claims as `1|claim\n2|claim\n...` and sends to Researcher Master
- Later, receives `FINAL_REPORT` from Reporter and forwards it to Gateway

**LLM:** GPT-4o-mini (AIML API)  
**System prompt focus:** Extract only verifiable factual claims; discard opinions, predictions, and rhetorical statements.

---

### Researcher Master

**Role:** Claim distribution and own-share research.

- Receives the numbered claim list from Orchestrator
- Dispatches a share of claims to ResearcherB, ResearcherC, and ResearcherD via REST messages
- Researches its own assigned claims: runs Tavily web search (5 results per claim) + GPT-4o-mini analysis
- Sends findings to Source Validator as `BULGULAR` (findings) block

**LLM:** GPT-4o-mini (AIML API) for analysis  
**Search:** Tavily API (general web, 5 results/claim)

---

### Researcher B

**Role:** Parallel web research (general).

- Receives a claim subset from Researcher Master
- Runs Tavily web search + GPT-4o-mini analysis per claim
- Sends findings to Source Validator

**LLM:** GPT-4o-mini (AIML API)  
**Search:** Tavily API (general web, 5 results/claim)

---

### Researcher C

**Role:** Parallel web research (general).

- Identical pipeline to Researcher B, different claim subset
- Increases coverage breadth by running independently

**LLM:** GPT-4o-mini (AIML API)  
**Search:** Tavily API (general web, 5 results/claim)

---

### Researcher D

**Role:** Parallel academic research.

- Receives a claim subset from Researcher Master
- Runs Tavily search restricted to academic domains: `arxiv.org`, `pubmed.ncbi.nlm.nih.gov`, `dergipark.org.tr`, `scholar.google.com`, `researchgate.net`, `jstor.org`, etc.
- Falls back to general web search if academic results are sparse
- Sends findings to Source Validator

**LLM:** GPT-4o-mini (AIML API)  
**Search:** Tavily API (academic domains first, general fallback)

---

### Source Validator

**Role:** Consensus analysis across all researcher findings.

- Waits until it has received findings from all 4 researchers (tracks by TASK_ID)
- Merges all findings and runs a GPT-4o-mini consensus pass to detect contradictions, corroborate sources, and assign preliminary confidence signals
- Sends the validated, merged findings to Reporter

**LLM:** GPT-4o-mini (AIML API)  
**System prompt focus:** Cross-reference findings, flag contradictions, weight academic sources higher, produce a structured analysis block per claim.

---

### Reporter

**Role:** Final report generation.

- Receives the validated findings from Source Validator
- Generates a structured plain-text report using Gemma 4 26B (Featherless)
- Report format:

```
TASK_ID: <id>

CLAIMS:
1. <claim text>
2. <claim text>

AVERAGE SCORE: 78/100

RESULTS:
1. <claim text>
Score: 92/100 | Verdict: TRUE
Analysis: <one-paragraph rationale>

2. <claim text>
Score: 54/100 | Verdict: PARTIALLY_TRUE
Analysis: ...

SUMMARY:
<overall assessment paragraph>

SOURCES:
- Source Title — https://example.com/article
- ...
```

**LLM:** Gemma 4 26B (Featherless API)  
**System prompt focus:** Structured plain-text output only, no markdown, follow the exact format above.

---

## Inter-Agent Message Protocol

All messages are plain text with uppercase keyword lines. Each agent filters incoming messages by checking for its own handle name and a domain-specific keyword.

| From | To | Key markers |
|---|---|---|
| Gateway | Orchestrator | `task_id:`, `please analyze` |
| Orchestrator | Researcher Master | `task_id:`, `claims:` |
| Researcher Master | B / C / D | `task_id:`, `researcher:`, `claims:` |
| Researchers | Source Validator | `task_id:`, `researcher:`, `bulgular` |
| Source Validator | Reporter | `task_id:`, `=== kaynak dogrulama ===` |
| Reporter | Orchestrator | `task_id:`, `final_report` |
| Orchestrator | Gateway | `task_id:`, `final_report`, `gateway` |

---

## Band SDK Behavior — Critical Note

`is_session_bootstrap=True` is set on **every agent's first message per session**, not only during history replay. All agents apply this guard:

```python
if is_session_bootstrap and len(history) > 0:
    return  # skip only real old history, not the first live message
```

Without the `len(history) > 0` check, the very first live request is silently dropped.

---

## LLM Summary

| Agent | Model | Provider | Purpose |
|---|---|---|---|
| Orchestrator | gpt-4o-mini | AIML API | Claim extraction |
| Researcher Master | gpt-4o-mini | AIML API | Web search analysis |
| Researcher B | gpt-4o-mini | AIML API | Web search analysis |
| Researcher C | gpt-4o-mini | AIML API | Web search analysis |
| Researcher D | gpt-4o-mini | AIML API | Academic search analysis |
| Source Validator | gpt-4o-mini | AIML API | Consensus + contradiction detection |
| Reporter | Gemma 4 26B | Featherless | Plain-text report generation |
| Gateway | — | — | Message routing only |
