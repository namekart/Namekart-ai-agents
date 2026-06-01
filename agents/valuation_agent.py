import json
from uuid import uuid4

from app.config import settings
from agents.llm_client import make_instructor_client
from prompts.valuation import VALUATION_SYSTEM, VALUATION_USER
from schemas.valuation import DomainDecision, ValuationReport


client = make_instructor_client()


def run_valuation_agent(domain_batch: list[dict], batch_id: str | None = None) -> ValuationReport:
    """
    Runs final grouped valuation for a batch of domains.

    Expected item shape:
    {
        "domain_name": str,
        "auction_price": float,
        "auction_bidders": int,
        "linguistic_report": LinguisticReport | dict,
        "market_report": MarketResearchReport | dict,
    }
    """
    if not domain_batch:
        raise ValueError("domain_batch must not be empty")

    normalized_batch = [_normalize_domain_item(item) for item in domain_batch]
    resolved_batch_id = batch_id or f"batch-{uuid4().hex[:8]}"

    if not settings.use_llm_valuation:
        return _fallback_valuation_report(normalized_batch, resolved_batch_id)

    messages = [
        {"role": "system", "content": VALUATION_SYSTEM},
        {
            "role": "user",
            "content": VALUATION_USER.format(
                batch_id=resolved_batch_id,
                domain_batch=json.dumps(normalized_batch, ensure_ascii=False, indent=2),
            ),
        },
    ]

    try:
        report = client.chat.completions.create(
            model=settings.model_pro,
            response_model=ValuationReport,
            messages=messages,
            max_retries=3,
        )
        sanitized = _sanitize_report(report, resolved_batch_id)
        if _report_domain_names(sanitized) != {item["domain_name"] for item in normalized_batch}:
            return _merge_with_fallback(sanitized, normalized_batch, resolved_batch_id)
        return sanitized
    except Exception as exc:
        print(
            f"Valuation agent failed for {resolved_batch_id}; "
            f"using fallback ({type(exc).__name__})."
        )
        return _fallback_valuation_report(normalized_batch, resolved_batch_id)


def _normalize_domain_item(item: dict) -> dict:
    domain_name = str(item["domain_name"]).strip().lower()
    linguistic_report = _dump_model_or_dict(item["linguistic_report"])
    market_report = _dump_model_or_dict(item["market_report"])

    return {
        "domain_name": domain_name,
        "auction_price": float(item.get("auction_price", 0) or 0),
        "auction_bidders": int(item.get("auction_bidders", 0) or 0),
        "linguistic_report": linguistic_report,
        "market_report": market_report,
    }


def _dump_model_or_dict(value: object) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    raise TypeError("report values must be Pydantic models or dictionaries")


def _sanitize_report(report: ValuationReport, batch_id: str) -> ValuationReport:
    report.batch_id = batch_id
    for decision in report.strong_buy:
        decision.decision = "STRONG_BUY"
    for bucket_name, tier in (("buy", "BUY"), ("maybe", "MAYBE"), ("skip", "SKIP")):
        for decision in getattr(report, bucket_name):
            decision.decision = tier
    return report


def _report_domain_names(report: ValuationReport) -> set[str]:
    names: set[str] = set()
    for bucket_name in ("strong_buy", "buy", "maybe", "skip"):
        names.update(decision.domain_name for decision in getattr(report, bucket_name))
    return names


def _merge_with_fallback(
    report: ValuationReport,
    domain_batch: list[dict],
    batch_id: str,
) -> ValuationReport:
    fallback = _fallback_valuation_report(domain_batch, batch_id)
    seen = _report_domain_names(report)

    for bucket_name in ("strong_buy", "buy", "maybe", "skip"):
        bucket = getattr(report, bucket_name)
        for decision in getattr(fallback, bucket_name):
            if decision.domain_name not in seen:
                bucket.append(decision)
                seen.add(decision.domain_name)
    return report


def _fallback_valuation_report(domain_batch: list[dict], batch_id: str) -> ValuationReport:
    scored_items = []
    for item in domain_batch:
        score = _weighted_score(item)
        decision = _decision_for_item(item, score)
        scored_items.append({**item, "weighted_score": score, "decision": decision})

    # Keep STRONG_BUY selective for the batch-level output strategy.
    strong_candidates = [
        item for item in scored_items if item["decision"] == "STRONG_BUY"
    ]
    strong_candidates.sort(key=lambda item: item["weighted_score"], reverse=True)
    max_strong = max(1, round(len(scored_items) * 0.05)) if len(scored_items) >= 20 else len(strong_candidates)
    allowed_strong = {item["domain_name"] for item in strong_candidates[:max_strong]}

    buckets = {"STRONG_BUY": [], "BUY": [], "MAYBE": [], "SKIP": []}
    for item in scored_items:
        decision = item["decision"]
        if decision == "STRONG_BUY" and item["domain_name"] not in allowed_strong:
            decision = "BUY"
        buckets[decision].append(item)

    return ValuationReport(
        batch_id=batch_id,
        strong_buy=[
            DomainDecision(
                domain_name=item["domain_name"],
                decision="STRONG_BUY",
            )
            for item in buckets["STRONG_BUY"]
        ],
        buy=[
            DomainDecision(domain_name=item["domain_name"], decision="BUY")
            for item in buckets["BUY"]
        ],
        maybe=[
            DomainDecision(domain_name=item["domain_name"], decision="MAYBE")
            for item in buckets["MAYBE"]
        ],
        skip=[
            DomainDecision(domain_name=item["domain_name"], decision="SKIP")
            for item in buckets["SKIP"]
        ],
    )


def _weighted_score(item: dict) -> float:
    linguistic = item["linguistic_report"]
    market = item["market_report"]
    linguistic_score = float(linguistic.get("overall_linguistic_score", 0))
    market_score = _market_score(market)
    future_score = _future_potential_score(market)
    roi_score = _roi_score(item)
    return round(
        linguistic_score * 0.30
        + market_score * 0.30
        + future_score * 0.25
        + roi_score * 0.15,
        2,
    )


def _market_score(market: dict) -> int:
    trajectory = market.get("market_trajectory", "unknown")
    base = {
        "growing": 8,
        "stable": 6,
        "declining": 3,
        "unknown": 2,
    }.get(trajectory, 2)
    funding = str(market.get("funding_activity", "")).lower()
    if any(word in funding for word in ("series", "funding", "ipo", "acquisition", "raised")):
        base += 1
    return min(base, 10)


def _future_potential_score(market: dict) -> int:
    if market.get("needs_manual_review"):
        return 3
    trajectory = market.get("market_trajectory", "unknown")
    demand = str(market.get("demand_signals", "")).lower()
    base = {
        "growing": 8,
        "stable": 6,
        "declining": 3,
        "unknown": 2,
    }.get(trajectory, 2)
    if any(word in demand for word in ("adoption", "demand", "growth", "jobs", "coverage")):
        base += 1
    return min(base, 10)


def _roi_score(item: dict) -> int:
    price = float(item.get("auction_price", 0) or 0)
    bidders = int(item.get("auction_bidders", 0) or 0)
    if price < 50:
        score = 10
    elif price <= 150:
        score = 8
    elif price <= 300:
        score = 6
    elif price <= 500:
        score = 4
    else:
        score = 2
    if bidders >= 1:
        score += 2
    return min(score, 10)


def _decision_for_item(item: dict, weighted_score: float) -> str:
    market = item["market_report"]
    market_exists = bool(market.get("market_exists", False))
    manual_review = bool(market.get("needs_manual_review", False))
    bidders = int(item.get("auction_bidders", 0) or 0)

    if not market_exists:
        return "MAYBE" if manual_review else "SKIP"
    if weighted_score >= 7.5 and not manual_review:
        return "STRONG_BUY"
    if weighted_score >= 6.0 or (bidders >= 1 and weighted_score >= 5.0):
        return "BUY"
    if weighted_score >= 4.5 or manual_review:
        return "MAYBE"
    return "SKIP"
