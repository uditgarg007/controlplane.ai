import time
from loguru import logger
from typing import Any

_ddgs_available = False
try:
    from ddgs import DDGS
    _ddgs_available = True
except ImportError:
    logger.warning("duckduckgo-search not installed. Web retrieval will fall back to mocks.")


def search_web(query: str, max_results: int = 3) -> list[dict[str, Any]]:
    """
    Perform a free web search using DuckDuckGo.
    Returns a list of dictionaries with 'title', 'href', and 'body' (snippet).

    No API key required — DuckDuckGo is completely free and unlimited.
    """
    if not _ddgs_available:
        return [
            {
                "title": "Mock Web Result",
                "href": "https://example.com/mock",
                "body": "This is a mock web search result because duckduckgo-search is not installed."
            }
        ]
        
    try:
        t0 = time.perf_counter()
        ddgs = DDGS()
        results = list(ddgs.text(query, max_results=max_results))
        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(f"Web search for '{query}' returned {len(results)} results in {elapsed:.1f}ms")
        return results
    except Exception as exc:
        logger.error(f"Web search failed for query '{query}': {exc}")
        return []
