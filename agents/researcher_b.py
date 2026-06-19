"""
ResearcherB -- SimpleAdapter, no LangGraph.
Receives claim list from ResearcherMaster, researches with Tavily+LLM, sends to SourceValidator.
"""
import asyncio
import concurrent.futures
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
from utils.tavily_client import search as tavily_search

load_dotenv()

logger = logging.getLogger(__name__)

RESEARCHER_ID = "b"

AIML_API_KEY = os.getenv("AIML_API_KEY")
AIML_API_BASE = os.getenv("AIML_API_BASE", "https://api.aimlapi.com/v1")
AIML_MODEL = os.getenv("AIML_MODEL", "openai/gpt-4o-mini")

REST_URL = os.getenv("THENVOI_REST_URL", "https://app.band.ai")
AGENT_ID = os.getenv("RESEARCHER_B_AGENT_ID")
API_KEY = os.getenv("RESEARCHER_B_API_KEY")
ROOM_ID = os.getenv("BAND_CHAT_ROOM_ID")
SOURCE_VALIDATOR_AGENT_ID = os.getenv("SOURCE_VALIDATOR_AGENT_ID")
SOURCE_VALIDATOR_HANDLE = os.getenv("SOURCE_VALIDATOR_HANDLE", "@suleymankaracakod/sourcevalidator")
RESEARCHER_B_HANDLE = os.getenv("RESEARCHER_B_HANDLE", "@suleymankaracakod/researcherb")

ANALYSIS_PROMPT = """You are a fact-checking researcher. Web search results for the following claim are provided.
Based on the results, evaluate the accuracy of the claim.

Claim: {claim}

Search Results:
{search_results}

Respond in this exact format:
Analysis: [2-3 sentences: what evidence supports or refutes the claim?]
Support Score: [integer 0-100 -- 100=definitely true, 0=definitely false, 50=unclear]
Reliable Sources: [source URLs if available, comma-separated, or "none found"]"""


def _analyze_claim(claim: str, search_results: str) -> str:
    client = OpenAI(api_key=AIML_API_KEY, base_url=AIML_API_BASE)
    resp = client.chat.completions.create(
        model=AIML_MODEL,
        messages=[{
            "role": "user",
            "content": ANALYSIS_PROMPT.format(claim=claim, search_results=search_results),
        }],
        temperature=0.1,
        max_tokens=600,
    )
    return resp.choices[0].message.content or "Analysis failed."


def _research_one(claim: str) -> str:
    logger.info(f"[ResearcherB] Researching: {claim[:70]}...")
    try:
        search_results = tavily_search(claim, max_results=5)
    except Exception as e:
        search_results = f"Search error: {e}"
    try:
        analysis = _analyze_claim(claim, search_results)
    except Exception as e:
        analysis = f"Analysis error: {e}\nRaw results:\n{search_results}"
    return f"Claim: {claim}\n{analysis}"


def _parse_task(content: str) -> tuple[str, list[str]]:
    task_id = ""
    claims = []
    in_claims = False

    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.upper().startswith("TASK_ID:"):
            task_id = stripped.split(":", 1)[1].strip()
        elif stripped.upper() == "CLAIMS:":
            in_claims = True
        elif in_claims and stripped:
            if stripped.lower().startswith("empty"):
                break
            if "|" in stripped:
                claim = stripped.split("|", 1)[1].strip()
                if claim:
                    claims.append(claim)
            elif re.match(r"^\d+[.)]\s+", stripped):
                claim = re.sub(r"^\d+[.)]\s+", "", stripped).strip()
                if claim:
                    claims.append(claim)

    return task_id, claims


def _research_and_send(task_id: str, claims: list[str]):
    if not claims:
        findings = "No claims assigned to this researcher."
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(claims), 6)) as ex:
            parts = list(ex.map(_research_one, claims))
        findings = "\n\n---\n\n".join(parts)

    content = (
        f"{SOURCE_VALIDATOR_HANDLE}\n\n"
        f"TASK_ID: {task_id}\n"
        f"RESEARCHER: {RESEARCHER_ID}\n"
        f"BULGULAR:\n{findings}"
    )

    client = RestClient(api_key=API_KEY, base_url=REST_URL)
    client.agent_api_messages.create_agent_chat_message(
        ROOM_ID,
        message=ChatMessageRequest(
            content=content,
            mentions=[ChatMessageRequestMentionsItem(id=SOURCE_VALIDATOR_AGENT_ID)],
        ),
    )
    logger.info(f"[ResearcherB] TASK_ID={task_id} -- findings sent to SourceValidator")


class ResearcherBAdapter(SimpleAdapter):
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

        if "researcherb" not in content_lower:
            return
        if "task_id:" not in content_lower:
            return
        if "claims:" not in content_lower:
            return

        task_id, claims = _parse_task(content)

        if not task_id:
            logger.warning("[ResearcherB] TASK_ID not found")
            return

        logger.info(f"[ResearcherB] TASK_ID={task_id} -- {len(claims)} claims received")

        threading.Thread(
            target=_research_and_send,
            args=(task_id, claims),
            daemon=True,
        ).start()


def start():
    def _run():
        adapter = ResearcherBAdapter()
        agent = Agent.create(adapter=adapter, agent_id=AGENT_ID, api_key=API_KEY)
        logger.info("[ResearcherB] Started (SimpleAdapter / Tavily+LLM)")
        asyncio.run(agent.run())

    t = threading.Thread(target=_run, daemon=True, name="researcher-b")
    t.start()
