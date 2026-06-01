"""
APR bridge — optional integration with APR-Prediction-Agent.

DISABLED in the default pipeline (bulk classifier + linguistic agent only).
`run_apr_bridge_batch` is a no-op; helper functions remain for tests.
"""

from __future__ import annotations

import re
import structlog

from schemas.apr_result import APRResult
from schemas.market import MarketResearchReport

logger = structlog.get_logger()


def _parse_dollar(value: str) -> float:
    """Convert '$1,250' or '$1,000 - $2,000' → 1250.0 (first number only)."""
    if not value:
        return 0.0
    try:
        match = re.search(r"\$?([\d,]+)", str(value))
        if match:
            cleaned = match.group(1).replace(",", "")
            return float(cleaned) if cleaned else 0.0
        return 0.0
    except (ValueError, TypeError):
        return 0.0


def _infer_trajectory(apr_result: dict, confidence: str) -> str:
    """Infer market_trajectory from APR agent reasoning text."""
    pred = apr_result.get("apr_prediction") or {}
    reasoning = str(pred.get("reasoning", "") if isinstance(pred, dict) else "").lower()

    if any(w in reasoning for w in ("growth", "growing", "rising", "cagr", "funding", "vc ")):
        return "growing"
    if any(w in reasoning for w in ("declining", "shrinking", "falling", "weak demand")):
        return "declining"
    if apr_result.get("similar_domains"):
        return "stable"
    return "unknown"


def apr_result_to_market_report(result: APRResult) -> MarketResearchReport:
    """Convert APRResult → MarketResearchReport (for tests / future use)."""
    cagr = {
        "growing": "12-25% (estimated from comparable domain sales)",
        "stable": "5-12% (estimated)",
        "declining": "< 5% (weak signals)",
        "unknown": "unknown",
    }.get(result.market_trajectory, "unknown")

    if result.similar_domains_count > 0:
        funding_activity = (
            f"Found {result.similar_domains_count} comparable domains in historical database "
            f"with confidence {result.confidence}"
        )
    else:
        funding_activity = "No comparable historical domains found in semantic database"

    demand_signals = result.reasoning_summary[:200] if result.reasoning_summary else (
        "No demand signals derived from comparable domain analysis"
    )

    raw_summary = (
        f"APR prediction: {result.predicted_apr:.0f} "
        f"(range {result.apr_range_low:.0f}-{result.apr_range_high:.0f}) | "
        f"Category: {result.domain_category} | "
        f"Comparables: {result.similar_domains_count} | "
        f"Confidence: {result.confidence}"
    )

    return MarketResearchReport(
        domain_name=result.domain_name,
        market_exists=result.market_exists,
        market_trajectory=result.market_trajectory,
        cagr_estimate=cagr,
        funding_activity=funding_activity,
        demand_signals=demand_signals,
        needs_manual_review=result.needs_manual_review,
        raw_search_summary=raw_summary,
    )


def run_apr_bridge_batch(domains: list[dict]) -> tuple[list[APRResult], list[MarketResearchReport]]:
    """No-op — pipeline does not call APR / Chroma / description LLMs."""
    logger.info("APR bridge skipped (two-agent pipeline)", domain_count=len(domains))
    return [], []
