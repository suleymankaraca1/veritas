"""
Gateway -- Bridge between Flask and Band platform.
No LLM calls. Sends task to Orchestrator, waits for final report.
"""
import asyncio
import logging
import os
import threading
import uuid

from dotenv import load_dotenv
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

REST_URL = os.getenv("THENVOI_REST_URL", "https://app.band.ai")
AGENT_ID = os.getenv("GATEWAY_AGENT_ID")
API_KEY = os.getenv("GATEWAY_API_KEY")
ROOM_ID = os.getenv("BAND_CHAT_ROOM_ID")
ORCHESTRATOR_AGENT_ID = os.getenv("ORCHESTRATOR_AGENT_ID")
ORCHESTRATOR_HANDLE = os.getenv("ORCHESTRATOR_HANDLE", "@suleymankaracakod/orchestrator")
GATEWAY_HANDLE = os.getenv("GATEWAY_HANDLE", "@suleymankaracakod/gateway")

_lock = threading.Lock()
_events: dict[str, threading.Event] = {}
_results: dict[str, dict] = {}


def analyze(text: str, timeout: int = 900) -> dict | None:
    task_id = str(uuid.uuid4())[:8]
    event = threading.Event()
    with _lock:
        _events[task_id] = event

    _send_rest(task_id, text)
    logger.info(f"[Gateway] TASK_ID={task_id} sent, waiting for response...")

    received = event.wait(timeout=timeout)
    with _lock:
        _events.pop(task_id, None)
        result = _results.pop(task_id, None)

    if not received or result is None:
        logger.error(f"[Gateway] TASK_ID={task_id} timeout or no result")
        return None
    return result


def _send_rest(task_id: str, text: str):
    content = (
        f"{ORCHESTRATOR_HANDLE}\n\n"
        f"TASK_ID: {task_id}\n\n"
        f"Please analyze all verifiable factual claims in the following text:\n\n{text}"
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
        logger.info(f"[Gateway] REST message sent (TASK_ID={task_id})")
    except Exception as e:
        logger.error(f"[Gateway] REST send error: {e}")


class GatewayAdapter(SimpleAdapter):
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
        gateway_tag = GATEWAY_HANDLE.lower().split("/")[-1]

        if gateway_tag not in content.lower():
            return

        task_id = None
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.upper().startswith("TASK_ID:"):
                task_id = stripped.split(":", 1)[1].strip()
                break

        if not task_id:
            logger.warning("[Gateway] TASK_ID not found in final report")
            return

        with _lock:
            if task_id not in _events:
                logger.warning(f"[Gateway] Unexpected TASK_ID: {task_id}")
                return
            _results[task_id] = {"task_id": task_id, "report": content}
            _events[task_id].set()

        logger.info(f"[Gateway] TASK_ID={task_id} final report received")


def start():
    def _run():
        adapter = GatewayAdapter()
        agent = Agent.create(adapter=adapter, agent_id=AGENT_ID, api_key=API_KEY)
        logger.info("[Gateway] Connecting to Band...")
        asyncio.run(agent.run())

    t = threading.Thread(target=_run, daemon=True, name="gateway")
    t.start()
    logger.info("[Gateway] Started")
