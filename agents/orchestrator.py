"""
Orchestrator -- SimpleAdapter, no LangGraph.
Task 1: Receives text from Gateway, extracts claims via gpt-4o-mini, sends to ResearcherMaster.
Task 2: Receives FINAL_REPORT from Reporter, forwards to Gateway.
"""
import asyncio
import logging
import os
import re
import threading

from dotenv import load_dotenv
from openai import OpenAI
from thenvoi_rest import RestClient, ChatMessageRequest, ChatMessageRequestMentionsItem
from band.core.simple_adapter import SimpleAdapter
from band.core.types import PlatformMessage
from band import Agent

load_dotenv()

logger = logging.getLogger(__name__)

AIML_API_KEY = os.getenv("AIML_API_KEY")
AIML_API_BASE = os.getenv("AIML_API_BASE", "https://api.aimlapi.com/v1")
AIML_MODEL = os.getenv("AIML_MODEL", "openai/gpt-4o-mini")

REST_URL = os.getenv("THENVOI_REST_URL", "https://app.band.ai")
AGENT_ID = os.getenv("ORCHESTRATOR_AGENT_ID")
API_KEY = os.getenv("ORCHESTRATOR_API_KEY")
ROOM_ID = os.getenv("BAND_CHAT_ROOM_ID")

RESEARCHER_MASTER_AGENT_ID = os.getenv("RESEARCHER_MASTER_AGENT_ID")
RESEARCHER_MASTER_HANDLE = os.getenv("RESEARCHER_MASTER_HANDLE", "@suleymankaracakod/researchermaster")
GATEWAY_AGENT_ID = os.getenv("GATEWAY_AGENT_ID")
GATEWAY_HANDLE = os.getenv("GATEWAY_HANDLE", "@suleymankaracakod/gateway")
ORCHESTRATOR_HANDLE = os.getenv("ORCHESTRATOR_HANDLE", "@suleymankaracakod/orchestrator")

CLAIM_PROMPT = """Extract all verifiable factual claims from the text below.
INCLUDE: numerical claims, historical facts, scientific claims, statistics, geographic facts.
EXCLUDE: personal opinions, subjective evaluations.
Maximum 12 claims. Find at least 1 claim.

Text:
{text}

Response format (use ONLY this format, nothing else):
Claim 1: [claim text]
Claim 2: [claim text]"""


def _extract_claims(text: str) -> list[str]:
    client = OpenAI(api_key=AIML_API_KEY, base_url=AIML_API_BASE)
    resp = client.chat.completions.create(
        model=AIML_MODEL,
        messages=[{"role": "user", "content": CLAIM_PROMPT.format(text=text)}],
        temperature=0.0,
        max_tokens=1024,
    )
    raw = resp.choices[0].message.content or ""
    logger.info(f"[Orchestrator] LLM claim output:\n{raw[:500]}")

    claims = re.findall(r"Claim\s*\d+\s*:\s*(.+)", raw, re.IGNORECASE)
    if not claims:
        claims = re.findall(r"^\d+[.)]\s+(.+)", raw, re.MULTILINE)
    return [c.strip() for c in claims if c.strip()]


def _send_rest(agent_id: str, content: str):
    client = RestClient(api_key=API_KEY, base_url=REST_URL)
    client.agent_api_messages.create_agent_chat_message(
        ROOM_ID,
        message=ChatMessageRequest(
            content=content,
            mentions=[ChatMessageRequestMentionsItem(id=agent_id)],
        ),
    )


def _handle_initial_task(task_id: str, user_text: str):
    try:
        claims = _extract_claims(user_text)
        if not claims:
            logger.warning(f"[Orchestrator] TASK_ID={task_id} no claims extracted, using raw text")
            claims = [user_text.strip()[:400]]

        logger.info(f"[Orchestrator] TASK_ID={task_id} -- {len(claims)} claims: {claims}")

        claims_text = "\n".join(f"{i+1}|{c}" for i, c in enumerate(claims))
        content = (
            f"{RESEARCHER_MASTER_HANDLE}\n\n"
            f"TASK_ID: {task_id}\n"
            f"CLAIMS:\n{claims_text}"
        )
        _send_rest(RESEARCHER_MASTER_AGENT_ID, content)
        logger.info(f"[Orchestrator] TASK_ID={task_id} -- sent to ResearcherMaster")
    except Exception as e:
        logger.error(f"[Orchestrator] TASK_ID={task_id} task error: {e}", exc_info=True)


def _handle_final_report(task_id: str, report_body: str):
    try:
        content = (
            f"{GATEWAY_HANDLE}\n\n"
            f"TASK_ID: {task_id}\n"
            f"FINAL_REPORT\n\n{report_body}"
        )
        _send_rest(GATEWAY_AGENT_ID, content)
        logger.info(f"[Orchestrator] TASK_ID={task_id} FINAL_REPORT forwarded to Gateway")
    except Exception as e:
        logger.error(f"[Orchestrator] TASK_ID={task_id} Gateway forward error: {e}", exc_info=True)


class OrchestratorAdapter(SimpleAdapter):
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

        if "orchestrator" not in content_lower:
            return
        if "task_id:" not in content_lower:
            return

        task_id = None
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.upper().startswith("TASK_ID:"):
                task_id = stripped.split(":", 1)[1].strip()
                break

        if not task_id:
            logger.warning("[Orchestrator] TASK_ID not found")
            return

        # Scenario 2: FINAL_REPORT from Reporter -> forward to Gateway
        if "final_report" in content_lower:
            logger.info(f"[Orchestrator] TASK_ID={task_id} FINAL_REPORT received")
            idx = content_lower.find("final_report")
            end_of_line = content.find("\n", idx)
            report_body = content[end_of_line:].strip() if end_of_line != -1 else ""
            threading.Thread(
                target=_handle_final_report,
                args=(task_id, report_body),
                daemon=True,
            ).start()
            return

        # Scenario 1: Initial task from Gateway -> extract claims -> ResearcherMaster
        logger.info(f"[Orchestrator] TASK_ID={task_id} new task, extracting claims...")

        # Extract user text: everything after TASK_ID line that isn't a handle or keyword
        lines = content.split("\n")
        text_lines = []
        past_task_id = False
        for line in lines:
            stripped = line.strip()
            if stripped.upper().startswith("TASK_ID:"):
                past_task_id = True
                continue
            if past_task_id and stripped and not stripped.startswith("@"):
                # Skip the "Please analyze..." instruction line, keep the actual text
                if stripped.lower().startswith("please analyze"):
                    continue
                text_lines.append(line)

        user_text = "\n".join(text_lines).strip() or content

        threading.Thread(
            target=_handle_initial_task,
            args=(task_id, user_text),
            daemon=True,
        ).start()


def start():
    def _run():
        adapter = OrchestratorAdapter()
        agent = Agent.create(adapter=adapter, agent_id=AGENT_ID, api_key=API_KEY)
        logger.info("[Orchestrator] Started (SimpleAdapter / gpt-4o-mini)")
        asyncio.run(agent.run())

    t = threading.Thread(target=_run, daemon=True, name="orchestrator")
    t.start()
