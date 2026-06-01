import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import structlog
from typing import Iterable

from app.config import settings
from agents.llm_client import make_instructor_client
from prompts.market import MARKET_SYSTEM, MARKET_USER
from schemas.market import MarketResearchReport
from tools.tavily_search import search


logger = structlog.get_logger()
client = make_instructor_client()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def gather_searches(domain_names: list[str]) -> list[dict]:
    """Run Tavily searches for each domain.

    Returns a list of dicts:
        {"domain_name", "search_payload", "needs_manual_review"}
    """
    if not domain_names:
        return []

    max_workers = max(1, min(settings.max_concurrent_domains, len(domain_names)))
    indexed_results: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_gather_search_for_domain, domain): index
            for index, domain in enumerate(domain_names)
        }
        for future in as_completed(futures):
            indexed_results[futures[future]] = future.result()

    return [indexed_results[index] for index in range(len(domain_names))]


def _gather_search_for_domain(domain: str) -> dict:
    stem = _domain_stem(domain)
    payload = _run_market_searches(stem)
    relevant_count = sum(1 for item in payload if item["relevant"])
    needs_review = relevant_count == 0

    logger.info(
        "Market searches done",
        domain=domain,
        queries=len(payload),
        relevant=relevant_count,
    )

    return {
        "domain_name": domain,
        "search_payload": payload,
        "needs_manual_review": needs_review,
    }


def run_market_agent_batch(search_data: list[dict]) -> list[MarketResearchReport]:
    """Synthesize search results for multiple domains in one LLM call.

    ``search_data`` items come from :func:`gather_searches`.
    """
    if not search_data:
        return []

    fallback_only = [
        _fallback_market_report(d["domain_name"], d["search_payload"], d["needs_manual_review"])
        for d in search_data
        if d["needs_manual_review"] or not _has_relevant_search(d["search_payload"])
    ]
    llm_search_data = [
        d
        for d in search_data
        if not d["needs_manual_review"] and _has_relevant_search(d["search_payload"])
    ]

    if not settings.use_llm_market or not llm_search_data:
        return fallback_only

    # Build compact payload for the prompt
    domains_payload = json.dumps(
        [
            {
                "domain_name": d["domain_name"],
                "search_results": d["search_payload"],
            }
            for d in llm_search_data
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )

    messages = [
        {"role": "system", "content": MARKET_SYSTEM},
        {
            "role": "user",
            "content": MARKET_USER.format(domains_payload=domains_payload),
        },
    ]

    try:
        reports = client.chat.completions.create(
            model=settings.model_pro,
            response_model=Iterable[MarketResearchReport],
            messages=messages,
            max_retries=3,
        )
        result_map: dict[str, MarketResearchReport] = {}
        for r in reports:
            key = r.domain_name.strip().lower()
            r.domain_name = key
            result_map[key] = r

        final: list[MarketResearchReport] = []
        for d in llm_search_data:
            domain = d["domain_name"]
            if domain in result_map:
                report = result_map[domain]
                final.append(report)
            else:
                logger.warning("Market batch missing domain, using fallback", domain=domain)
                final.append(
                    _fallback_market_report(domain, d["search_payload"], d["needs_manual_review"])
                )
        return fallback_only + final

    except Exception as exc:
        logger.error("Market batch failed, using fallbacks", count=len(llm_search_data), error=str(exc))
        return fallback_only + [
            _fallback_market_report(d["domain_name"], d["search_payload"], d["needs_manual_review"])
            for d in llm_search_data
        ]


# ---------------------------------------------------------------------------
# Single-domain wrapper (backward compat)
# ---------------------------------------------------------------------------

def run_market_agent(domain_name: str) -> MarketResearchReport:
    """Convenience wrapper: analyse one domain via the batch path."""
    normalized = domain_name.strip().lower()
    search_data = gather_searches([normalized])
    results = run_market_agent_batch(search_data)
    return results[0]


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------

def _run_market_searches(stem: str) -> list[dict]:
    concept = _market_concept(stem)
    queries = [
        f"{concept} market growth funding",
        f"{concept} industry trend demand",
    ]

    return [_search_with_relevance(query, stem) for query in queries]


def _search_with_relevance(query: str, stem: str) -> dict:
    try:
        results = search(query, max_results=settings.market_search_results)
    except Exception as exc:
        logger.warning("Tavily search failed", query=query, error=str(exc))
        results = []

    compact_results = [_compact_result(result) for result in results]
    return {
        "query": query,
        "relevant": _results_look_relevant(stem, compact_results),
        "results": compact_results,
    }


def _compact_result(result: dict) -> dict:
    content = result.get("content", "")
    max_chars = settings.max_search_content_chars
    if len(content) > max_chars:
        content = content[:max_chars] + "..."
    return {
        "title": result.get("title", ""),
        "content": content,
    }


def _results_look_relevant(stem: str, results: list[dict]) -> bool:
    if not results:
        return False

    stem_tokens = set(_tokens(stem))
    stem_variants = _stem_variants(stem)
    if not stem_tokens:
        return False

    market_words = {
        "market", "industry", "growth", "startup", "funding",
        "trend", "technology", "software", "platform", "business",
        "research", "forecast",
    }

    for result in results:
        text = f"{result['title']} {result['content']}".lower()
        if any(variant in text for variant in stem_variants):
            return True
        if stem_tokens.intersection(_tokens(text)) and market_words.intersection(_tokens(text)):
            return True
    return False


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

def _fallback_market_report(
    domain_name: str,
    search_payload: list[dict],
    needs_manual_review: bool,
) -> MarketResearchReport:
    relevant_queries = [item for item in search_payload if item["relevant"]]
    has_results = any(item["results"] for item in search_payload)

    if needs_manual_review or not relevant_queries:
        return MarketResearchReport(
            domain_name=domain_name,
            market_exists=False,
            market_trajectory="unknown",
            cagr_estimate="unknown",
            funding_activity="no relevant funding signals found",
            demand_signals="no clear demand signals in search results",
            needs_manual_review=True,
            raw_search_summary=_summarize_search_payload(search_payload),
        )

    return MarketResearchReport(
        domain_name=domain_name,
        market_exists=has_results,
        market_trajectory="stable",
        cagr_estimate="8-15% (estimated)",
        funding_activity="search results found category signals; LLM synthesis unavailable",
        demand_signals="search results include market or industry references",
        needs_manual_review=False,
        raw_search_summary=_summarize_search_payload(search_payload),
    )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _summarize_search_payload(search_payload: list[dict]) -> str:
    summaries = []
    for item in search_payload[:4]:
        first_title = item["results"][0]["title"] if item["results"] else "no results"
        summaries.append(f"{item['query']}: {first_title}")
    return " | ".join(summaries)


def _has_relevant_search(search_payload: list[dict]) -> bool:
    return any(item["relevant"] and item["results"] for item in search_payload)


def _domain_stem(domain_name: str) -> str:
    return domain_name.split(".", 1)[0]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _market_concept(stem: str) -> str:
    variants = _stem_variants(stem)
    return variants[-1] if variants else stem


def _stem_variants(stem: str) -> list[str]:
    normalized = stem.lower()
    variants = [normalized]
    if normalized.endswith("ify") and len(normalized) > 5:
        variants.append(normalized[:-3])
    if normalized.endswith("ist") and len(normalized) > 5:
        variants.append(f"{normalized[:-3]}y")
    return variants
