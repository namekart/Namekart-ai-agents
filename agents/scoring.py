"""
Unified scoring and ranking for pipeline results.

All displayed scores (linguistic, market, valuation, final) are computed here
so CSV output is consistent and domains are ranked relative to each other,
not by fixed buckets that create repetitive patterns.
"""

from __future__ import annotations

import re
from typing import Any

from agents.domain_quality import adjusted_linguistic_score, parse_domain, stem_has_brand_keyword
from agents.linguistic_agent import evaluate_linguistic_gate


def normalize_domain_row(domain: dict) -> dict:
    """Ensure domain_name, tld, and numeric auction fields are present."""
    name = str(domain.get("domain_name") or domain.get("domain", "")).strip().lower()
    if not name:
        return domain
    features = parse_domain(name)
    return {
        **domain,
        "domain_name": name,
        "tld": domain.get("tld") or features.tld,
    }


def linguistic_display_score(ling_report: Any) -> float:
    """Adjusted overall score used for ranking (TLD-aware)."""
    if ling_report is None:
        return 0.0
    if hasattr(ling_report, "model_dump"):
        data = ling_report.model_dump()
    elif isinstance(ling_report, dict):
        data = ling_report
    else:
        return 0.0
    name = data.get("domain_name", "")
    overall = float(data.get("overall_linguistic_score", 0))
    features = parse_domain(name)
    return adjusted_linguistic_score(overall, features.tld)


def market_display_score(market_report: dict | None) -> float:
    """
    Continuous market score 1–10 from trajectory, evidence quality, and APR signals.
    Avoids only 1.0 / 7.0 / 10.0 plateaus from coarse rules.
    """
    if not market_report:
        return 1.0

    trajectory = market_report.get("market_trajectory", "unknown")
    base = {
        "growing": 7.5,
        "stable": 5.5,
        "declining": 2.5,
        "unknown": 2.0,
    }.get(trajectory, 2.0)

    if market_report.get("market_exists"):
        base += 1.0
    else:
        base -= 0.5

    if market_report.get("needs_manual_review"):
        base -= 1.5

    funding = str(market_report.get("funding_activity", "")).lower()
    if any(w in funding for w in ("comparable", "historical database", "confidence high")):
        base += 0.8
    elif any(w in funding for w in ("series", "funding", "raised", "ipo", "acquisition")):
        base += 0.5
    elif "no comparable" in funding or "fallback" in funding:
        base -= 1.0

    summary = str(market_report.get("raw_search_summary", "")).lower()
    if "comparables: 0" in summary or "confidence: low" in summary:
        base -= 1.0
    if "predicted_apr" in summary and "0" not in summary.split("|")[0]:
        base += 0.3

    demand = str(market_report.get("demand_signals", "")).lower()
    if len(demand) > 40 and demand not in ("no demand", "n/a"):
        base += 0.4

    return round(max(1.0, min(10.0, base)), 2)


def valuation_display_score(domain: dict, linguistic_score: float) -> float:
    """
    Auction ROI hint — secondary to linguistic quality for .ai acquisition lists.
    Does not dominate final_score (linguistic-led ranking).
    """
    domain = normalize_domain_row(domain)
    price = float(domain.get("auction_price", 0) or 0)
    bidders = int(domain.get("auction_bidders", 0) or 0)
    features = parse_domain(domain["domain_name"])
    stem = features.stem

    if price <= 0:
        price_score = 6.5
    elif price < 50:
        price_score = 8.5
    elif price < 120:
        price_score = 7.5
    elif price < 250:
        price_score = 6.5
    elif price < 500:
        price_score = 5.5
    elif price < 1000:
        price_score = 4.5
    else:
        price_score = 3.5

    bidder_score = min(1.5, bidders * 0.25)
    tld_bonus = {"com": 0.8, "net": 0.3, "io": 0.4, "ai": 1.0, "co": 0.2}.get(features.tld, -0.2)
    if features.tld in ("xyz", "top", "click", "info", "biz", "online"):
        tld_bonus = -2.0

    ling_component = linguistic_score * 0.25

    coined_penalty = 0.0
    if features.tld == "ai" and len(stem) <= 11:
        if re.search(r"(wise|hub|tech|soft|code|link|flow|ify|bot|gen|gpt)$", stem) and not stem_has_brand_keyword(stem):
            coined_penalty = 0.8

    score = price_score + bidder_score + tld_bonus + ling_component - coined_penalty

    if linguistic_score < 3.5:
        score -= 2.0
    elif linguistic_score < 5.0:
        score -= 1.0

    if features.has_dash or features.is_keyboard_mash or features.tld in ("xyz", "info", "top", "click"):
        score -= 1.5

    return round(max(1.0, min(10.0, score)), 2)


def composite_final_score(
    linguistic_score: float,
    market_score: float,
    valuation_score: float,
) -> float:
    return round(
        linguistic_score * 0.35
        + market_score * 0.35
        + valuation_score * 0.30,
        2,
    )


def assign_decision(
    final_score: float,
    linguistic_score: float,
    market_score: float,
    market_report: dict | None,
    *,
    tier: str | None = None,
) -> str:
    """Assign decision with absolute floors — tier is optional percentile label."""
    market_exists = bool(market_report and market_report.get("market_exists"))
    manual = bool(market_report and market_report.get("needs_manual_review"))

    if tier == "top":
        return "STRONG_BUY"
    if tier == "high":
        return "BUY"
    if tier == "mid":
        return "MAYBE"

    # Absolute rules when not using percentile tiers
    if final_score >= 7.8 and linguistic_score >= 7.5 and market_score >= 7.5 and market_exists:
        return "STRONG_BUY"
    if final_score >= 6.5 and linguistic_score >= 6.5 and market_score >= 5.5 and market_exists:
        return "BUY"
    if final_score >= 4.5 or manual:
        return "MAYBE"
    return "SKIP"


def rank_domains(
    candidates: list[dict],
    *,
    strong_buy_pct: float = 0.03,
    buy_pct: float = 0.10,
) -> list[dict]:
    """
    Rank candidates by composite score; assign decisions by relative quality.
    Each candidate dict must include: domain_name, final_score, linguistic_score,
    market_score, valuation_score, market_report (optional).
    """
    if not candidates:
        return []

    ranked = sorted(candidates, key=lambda x: x["final_score"], reverse=True)
    n = len(ranked)
    strong_slots = max(1, int(n * strong_buy_pct)) if n >= 10 else (1 if n else 0)
    buy_slots = max(strong_slots, int(n * (strong_buy_pct + buy_pct)))

    for i, row in enumerate(ranked):
        if i < strong_slots and row["final_score"] >= 7.0 and row["linguistic_score"] >= 6.5:
            row["decision"] = assign_decision(
                row["final_score"], row["linguistic_score"], row["market_score"],
                row.get("market_report"), tier="top",
            )
        elif i < buy_slots and row["final_score"] >= 5.8:
            row["decision"] = assign_decision(
                row["final_score"], row["linguistic_score"], row["market_score"],
                row.get("market_report"), tier="high",
            )
        elif row["final_score"] >= 4.0:
            row["decision"] = assign_decision(
                row["final_score"], row["linguistic_score"], row["market_score"],
                row.get("market_report"), tier="mid",
            )
        else:
            row["decision"] = "SKIP"

    return ranked


def build_candidate_scores(
    domain_rows: list[dict],
    linguistic_reports: dict,
    market_reports: dict,
) -> list[dict]:
    """Legacy: full pipeline with market reports. Prefer build_linguistic_only_candidates."""
    return build_linguistic_only_candidates(domain_rows, linguistic_reports, {})


def build_linguistic_only_candidates(
    domain_rows: list[dict],
    linguistic_reports: dict,
    bulk_reports: dict,
) -> list[dict]:
    """
    Score domains using bulk + linguistic agents only (no APR / Chroma / market LLM).
    Includes every domain that passed bulk and received a linguistic report.
    """
    candidates = []
    for domain in domain_rows:
        row = normalize_domain_row(domain)
        name = row["domain_name"]
        ling = linguistic_reports.get(name)
        if not ling:
            continue

        bulk = bulk_reports.get(name)
        bulk_score = getattr(bulk, "brandability_score", None) if bulk else None
        ling_score = linguistic_display_score(ling)
        val_score = valuation_display_score(row, ling_score)
        # Linguistic quality drives acquisition picks; auction price is a tie-breaker only
        final = round(ling_score * 0.82 + val_score * 0.18, 2)
        gate_passed, _, gate_detail = evaluate_linguistic_gate(ling)

        candidates.append({
            "domain_name": name,
            "linguistic_score": ling_score,
            "bulk_score": bulk_score,
            "valuation_score": val_score,
            "final_score": final,
            "gate_passed": gate_passed,
            "gate_detail": gate_detail or "",
            "auction_price": row.get("auction_price"),
            "auction_bidders": row.get("auction_bidders"),
        })
    return candidates


def assign_linguistic_decision(row: dict) -> str:
    """
    Merit-based tiers for .ai acquisition — not top-3% percentile slots.
    STRONG_BUY = clear brandable + strong linguistic + bulk pass.
    """
    if not row.get("gate_passed"):
        return "SKIP"

    ling = float(row.get("linguistic_score") or 0)
    bulk = float(row.get("bulk_score") or 0)
    features = parse_domain(row["domain_name"])
    branded = stem_has_brand_keyword(features.stem)

    if ling >= 7.2 and bulk >= 7:
        return "STRONG_BUY"
    if ling >= 6.9 and bulk >= 7 and branded:
        return "STRONG_BUY"
    if ling >= 7.0 and bulk >= 7:
        return "BUY"
    if ling >= 6.5 and bulk >= 6:
        return "BUY"
    if ling >= 6.0:
        return "MAYBE"
    return "SKIP"


def rank_domains_linguistic_only(candidates: list[dict]) -> list[dict]:
    """Assign decisions from linguistic + bulk merit; gate failures are SKIP."""
    if not candidates:
        return []

    for row in candidates:
        row["decision"] = assign_linguistic_decision(row)

    return sorted(candidates, key=lambda x: float(x.get("final_score") or 0), reverse=True)
