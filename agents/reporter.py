"""
Reporter -- Final report generation.
Model: Featherless AI / Gemma (direct OpenAI SDK, no LangGraph).
SimpleAdapter: on_message calls Featherless, sends result via REST to Orchestrator.
"""
import asyncio
import logging
import os
import threading

from dotenv import load_dotenv
from openai import OpenAI
from thenvoi_rest import (
    RestClient,
    ChatMessageRequest,
    ChatMessageRequestMentionsItem,
)
from band.core.simple_adapter import SimpleAdapter
from band.core.types import PlatformMessage
from band import Agent

load_dotenv()

logger = logging.getLogger(__name__)

_processed_tasks: set[str] = set()
_processed_lock = threading.Lock()

FEATHERLESS_API_KEY = os.getenv("FEATHERLESS_API_KEY")
FEATHERLESS_API_BASE = os.getenv("FEATHERLESS_API_BASE", "https://api.featherless.ai/v1")
FEATHERLESS_MODEL = os.getenv("FEATHERLESS_MODEL", "google/gemma-4-26B-A4B-it")

REST_URL = os.getenv("THENVOI_REST_URL", "https://app.band.ai")
AGENT_ID = os.getenv("REPORTER_AGENT_ID")
API_KEY = os.getenv("REPORTER_API_KEY")
ROOM_ID = os.getenv("BAND_CHAT_ROOM_ID")
ORCHESTRATOR_AGENT_ID = os.getenv("ORCHESTRATOR_AGENT_ID")
ORCHESTRATOR_HANDLE = os.getenv("ORCHESTRATOR_HANDLE", "@suleymankaracakod/orchestrator")
REPORTER_HANDLE = os.getenv("REPORTER_HANDLE", "@suleymankaracakod/reporter")

REPORT_PROMPT = """You are a fact-checking expert. Analyze the research findings below and produce a clear, readable verification report.

Research data:
{research_data}

Write the report in EXACTLY this plain-text format. Do NOT use JSON. Do NOT use markdown code blocks. No extra text outside this format:

TASK_ID: {task_id}

CLAIMS:
1. [first claim from the research data]
2. [second claim]
[list ALL claims found]

AVERAGE SCORE: [integer average of all confidence scores]/100

RESULTS:
1. [Claim 1 text]
   Score: [0-100]/100 | Verdict: [TRUE / FALSE / PARTIALLY_TRUE / UNCERTAIN]
   Analysis: [2-3 sentences: why this score? what evidence supports or refutes it?]

2. [Claim 2 text]
   Score: [0-100]/100 | Verdict: [TRUE / FALSE / PARTIALLY_TRUE / UNCERTAIN]
   Analysis: [2-3 sentences]

[continue for every claim]

SUMMARY:
[2-3 sentences: overall assessment — how many claims true/false/uncertain, notable findings or warnings]

SOURCES:
- [Source Title] — [URL]
- [Source Title] — [URL]
[list every unique source URL from all researchers, no duplicates]

Verdict guide: TRUE (score>70), FALSE (score<30), PARTIALLY_TRUE (score 30-70), UNCERTAIN (insufficient/conflicting sources)
"""


def _generate_report(task_id: str, research_data: str) -> str:
    client = OpenAI(api_key=FEATHERLESS_API_KEY, base_url=FEATHERLESS_API_BASE)
    prompt = REPORT_PROMPT.format(task_id=task_id, research_data=research_data)

    logger.info(f"[Reporter] TASK_ID={task_id} calling Featherless/Gemma...")
    response = client.chat.completions.create(
        model=FEATHERLESS_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=4096,
    )
    raw = response.choices[0].message.content or ""
    logger.info(f"[Reporter] Featherless response received ({len(raw)} chars)")
    return raw


def _send_to_orchestrator(task_id: str, report_text: str):
    content = (
        f"{ORCHESTRATOR_HANDLE}\n\n"
        f"TASK_ID: {task_id}\n"
        f"FINAL_REPORT\n\n"
        f"{report_text}"
    )
    try:
        client = RestClient(api_key=API_KEY, base_url=REST_URL)
        client.agent_api_messages.create_agent_chat_message(
            ROOM_ID,
            message=ChatMessageRequest(
                content=content,
                mentions=[ChatMessageRequestMentionsItem(id=ORCHESTRATOR_AGENT_ID)],
            ),
        )
        logger.info(f"[Reporter] TASK_ID={task_id} FINAL_REPORT sent to Orchestrator")
    except Exception as e:
        logger.error(f"[Reporter] REST send error: {e}")


class ReporterAdapter(SimpleAdapter):
    async def on_message(
        self,
        msg: PlatformMessage,
        tools,
        history,
        participants_msg,
        contacts_msg,
        *,
        is_session_bootstrap: bool,
        room_id: str,
    ) -> None:
        content = msg.content or ""
        content_lower = content.lower()

        reporter_tag = REPORTER_HANDLE.lower().split("/")[-1]
        if reporter_tag not in content_lower:
            return
        if "task_id:" not in content_lower:
            return
        if "bulgular" not in content_lower and "findings" not in content_lower and "verified" not in content_lower:
            return

        task_id = None
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.upper().startswith("TASK_ID:"):
                task_id = stripped.split(":", 1)[1].strip()
                break

        if not task_id:
            logger.warning("[Reporter] TASK_ID not found in message")
            return

        with _processed_lock:
            if task_id in _processed_tasks:
                logger.warning(f"[Reporter] TASK_ID={task_id} already processed, skipping")
                return
            _processed_tasks.add(task_id)

        logger.info(f"[Reporter] TASK_ID={task_id} processing...")

        try:
            report = _generate_report(task_id, content)
            _send_to_orchestrator(task_id, report)
        except Exception as e:
            logger.error(f"[Reporter] Processing error TASK_ID={task_id}: {e}")


def start():
    def _run():
        adapter = ReporterAdapter()
        agent = Agent.create(adapter=adapter, agent_id=AGENT_ID, api_key=API_KEY)
        logger.info("[Reporter] Started (SimpleAdapter/Featherless)")
        asyncio.run(agent.run())

    t = threading.Thread(target=_run, daemon=True, name="reporter")
    t.start()
