"""
SourceValidator -- Collects findings from 4 researchers, runs consensus analysis, forwards to Reporter.
SimpleAdapter: Python state management + gpt-4o-mini consensus analysis.
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

AIML_API_KEY = os.getenv("AIML_API_KEY")
AIML_API_BASE = os.getenv("AIML_API_BASE", "https://api.aimlapi.com/v1")
AIML_MODEL = os.getenv("AIML_MODEL", "openai/gpt-4o-mini")

REST_URL = os.getenv("THENVOI_REST_URL", "https://app.band.ai")
AGENT_ID = os.getenv("SOURCE_VALIDATOR_AGENT_ID")
API_KEY = os.getenv("SOURCE_VALIDATOR_API_KEY")
ROOM_ID = os.getenv("BAND_CHAT_ROOM_ID")
REPORTER_AGENT_ID = os.getenv("REPORTER_AGENT_ID")
REPORTER_HANDLE = os.getenv("REPORTER_HANDLE", "@suleymankaracakod/reporter")
SOURCE_VALIDATOR_HANDLE = os.getenv("SOURCE_VALIDATOR_HANDLE", "@suleymankaracakod/sourcevalidator")

_RESEARCHERS = {"master", "b", "c", "d"}

# Thread-safe state: { task_id: { "master": str|None, "b": str|None, ... } }
_store: dict[str, dict] = {}
_store_lock = threading.Lock()
_forwarded: set[str] = set()

CONSENSUS_PROMPT = """You are a source validation expert in the VERITAS fact-checking system.
4 independent researchers (Master, B, C, D) have investigated different claims and produced AI-assisted analyses.
All findings are below.

{findings}

Perform the following analysis:
1. Which claims were verified with high confidence? (Support Score > 70)
2. Which claims had weak or insufficient support? (Support Score < 50)
3. Which claims had poor source quality or no sources found?
4. Overall research quality assessment

Response format:
HIGH CONFIDENCE CLAIMS: [claim summaries and scores]
LOW CONFIDENCE CLAIMS: [claim summaries -- needs special attention]
SOURCE ISSUES: [problematic claims or "All claims had sources found"]
OVERALL ASSESSMENT: [2-3 sentences -- research quality and reliability status]"""


def _consensus_analysis(all_findings: str) -> str:
    client = OpenAI(api_key=AIML_API_KEY, base_url=AIML_API_BASE)
    resp = client.chat.completions.create(
        model=AIML_MODEL,
        messages=[{
            "role": "user",
            "content": CONSENSUS_PROMPT.format(findings=all_findings),
        }],
        temperature=0.1,
        max_tokens=800,
    )
    return resp.choices[0].message.content or "Consensus analysis failed."


def _record_finding(task_id: str, researcher: str, findings: str) -> bool:
    researcher = researcher.lower().strip()
    if researcher not in _RESEARCHERS:
        return False

    with _store_lock:
        if task_id not in _store:
            _store[task_id] = {r: None for r in _RESEARCHERS}
        _store[task_id][researcher] = findings
        done = [r for r, v in _store[task_id].items() if v is not None]
        missing = [r for r, v in _store[task_id].items() if v is None]

    logger.info(f"[SourceValidator] TASK_ID={task_id} -- {researcher} recorded. "
                f"Done: {done}, Pending: {missing}")
    return len(missing) == 0


def _get_all_findings(task_id: str) -> str:
    with _store_lock:
        data = _store.get(task_id, {})
    parts = []
    for r in ["master", "b", "c", "d"]:
        findings = data.get(r) or "(no findings)"
        parts.append(f"=== RESEARCHER: {r.upper()} ===\n{findings}")
    return "\n\n".join(parts)


def _send_to_reporter(task_id: str):
    with _store_lock:
        if task_id in _forwarded:
            logger.info(f"[SourceValidator] TASK_ID={task_id} already sent, skipping.")
            return
        _forwarded.add(task_id)

    all_findings = _get_all_findings(task_id)

    logger.info(f"[SourceValidator] TASK_ID={task_id} -- running consensus analysis...")
    try:
        consensus = _consensus_analysis(all_findings)
    except Exception as e:
        logger.error(f"[SourceValidator] Consensus analysis error: {e}")
        consensus = f"Consensus analysis failed: {e}"

    content = (
        f"{REPORTER_HANDLE}\n\n"
        f"TASK_ID: {task_id}\n"
        f"Verified bulgular (4 researchers complete):\n\n"
        f"{all_findings}\n\n"
        f"=== SOURCE VALIDATION ANALYSIS ===\n"
        f"{consensus}"
    )
    try:
        client = RestClient(api_key=API_KEY, base_url=REST_URL)
        client.agent_api_messages.create_agent_chat_message(
            ROOM_ID,
            message=ChatMessageRequest(
                content=content,
                mentions=[ChatMessageRequestMentionsItem(id=REPORTER_AGENT_ID)],
            ),
        )
        logger.info(f"[SourceValidator] TASK_ID={task_id} -> sent to Reporter (with consensus)")
    except Exception as e:
        logger.error(f"[SourceValidator] Reporter send error: {e}")
        with _store_lock:
            _forwarded.discard(task_id)


class SourceValidatorAdapter(SimpleAdapter):
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

        if "researcher:" not in content_lower:
            return
        if "task_id:" not in content_lower:
            return
        if "bulgular" not in content_lower and "findings" not in content_lower:
            return

        task_id = None
        researcher = None
        findings_lines = []
        in_findings = False

        for line in content.split("\n"):
            stripped = line.strip()
            upper = stripped.upper()

            if upper.startswith("TASK_ID:"):
                task_id = stripped.split(":", 1)[1].strip()
            elif upper.startswith("RESEARCHER:"):
                researcher = stripped.split(":", 1)[1].strip().lower()
            elif upper.startswith("BULGULAR:") or upper == "BULGULAR" or upper.startswith("FINDINGS:") or upper == "FINDINGS":
                in_findings = True
            elif in_findings:
                findings_lines.append(line)

        if not task_id or not researcher:
            return

        if researcher not in _RESEARCHERS:
            return

        findings = "\n".join(findings_lines).strip() or content

        all_done = _record_finding(task_id, researcher, findings)

        if all_done:
            threading.Thread(
                target=_send_to_reporter,
                args=(task_id,),
                daemon=True,
            ).start()


def start():
    def _run():
        adapter = SourceValidatorAdapter()
        agent = Agent.create(adapter=adapter, agent_id=AGENT_ID, api_key=API_KEY)
        logger.info("[SourceValidator] Started (SimpleAdapter / consensus analysis)")
        asyncio.run(agent.run())

    t = threading.Thread(target=_run, daemon=True, name="source-validator")
    t.start()
