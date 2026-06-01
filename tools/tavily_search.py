import time
import structlog

from tavily import TavilyClient

from app.config import settings

logger = structlog.get_logger()

client = TavilyClient(api_key=settings.tavily_api_key)

MAX_SEARCH_RETRIES = 3


def search(query: str, max_results: int = 3) -> list[dict]:
    """Run a Tavily search with retry + exponential backoff."""
    for attempt in range(MAX_SEARCH_RETRIES):
        try:
            response = client.search(query, max_results=max_results)
            return response.get("results", [])
        except Exception as exc:
            wait = 2 ** attempt  # 1s, 2s, 4s
            if attempt < MAX_SEARCH_RETRIES - 1:
                logger.warning(
                    "Tavily search failed, retrying",
                    query=query,
                    attempt=attempt + 1,
                    wait_seconds=wait,
                    error=str(exc),
                )
                time.sleep(wait)
            else:
                logger.error(
                    "Tavily search exhausted retries",
                    query=query,
                    error=str(exc),
                )
                raise
    return []  # unreachable, but keeps type checkers happy
