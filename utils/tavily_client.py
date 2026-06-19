import os
import logging
from tavily import TavilyClient

logger = logging.getLogger(__name__)

_client: TavilyClient | None = None


def get_client() -> TavilyClient:
    global _client
    if _client is None:
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            raise ValueError("TAVILY_API_KEY is missing")
        _client = TavilyClient(api_key=api_key)
    return _client


def search(query: str, max_results: int = 5) -> str:
    """Web search for a claim, returns formatted text."""
    try:
        client = get_client()
        response = client.search(query=query, max_results=max_results, search_depth="basic")
        results = response.get("results", [])
        if not results:
            return "No search results found."

        parts = []
        for r in results:
            title = r.get("title", "No title")
            url = r.get("url", "")
            content = r.get("content", "")[:600]
            parts.append(f"Title: {title}\nURL: {url}\nContent: {content}")

        return "\n\n---\n\n".join(parts)
    except Exception as e:
        logger.error(f"[Tavily] Search error: {e}")
        return f"Search error: {e}"


ACADEMIC_DOMAINS = [
    "scholar.google.com", "pubmed.ncbi.nlm.nih.gov", "arxiv.org",
    "researchgate.net", "ncbi.nlm.nih.gov", "sciencedirect.com",
    "springer.com", "nature.com", "wiley.com", "jstor.org",
    "academic.oup.com", "dergipark.org.tr", "trdizin.gov.tr",
]


def search_academic(query: str, max_results: int = 5) -> str:
    """Academic-domain search; falls back to general search if fewer than 2 results."""
    try:
        client = get_client()
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth="advanced",
            include_domains=ACADEMIC_DOMAINS,
        )
        results = response.get("results", [])
        if len(results) < 2:
            logger.info("[Tavily] Academic search returned few results, falling back to general.")
            return search(query, max_results=max_results)

        parts = []
        for r in results:
            title = r.get("title", "No title")
            url = r.get("url", "")
            content = r.get("content", "")[:600]
            parts.append(f"Title: {title}\nURL: {url}\nContent: {content}")

        return "\n\n---\n\n".join(parts)
    except Exception as e:
        logger.error(f"[Tavily] Academic search error: {e}")
        return search(query, max_results=max_results)
