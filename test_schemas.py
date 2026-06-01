import sys
import json
from schemas.bulk_filter import BulkFilterResult
from schemas.linguistic import LinguisticReport
from schemas.market import MarketResearchReport
from schemas.valuation import ValuationReport, DomainDecision

# Check 1: Imports work (implicitly passed if it reaches here)

# Check 2: Instantiate each schema and dump
bf = BulkFilterResult(domain_name="test.com", brandability_score=8, llm_filter_passed=True, llm_filter_reason="good")
assert bf.model_dump() is not None

lr = LinguisticReport(
    domain_name="test.com",
    pronounceability=8,
    memorability=8,
    spelling_ease=8,
    cross_language_safety=8,
    word_segmentation=8,
    brand_personality=8,
    industry_fit=8,
    novelty_score=8,
    overall_linguistic_score=8.0
)
assert lr.model_dump() is not None

mr = MarketResearchReport(
    domain_name="test.com",
    market_exists=True,
    market_trajectory="growing",
    cagr_estimate="12%",
    funding_activity="high",
    demand_signals="good",
    needs_manual_review=False,
    raw_search_summary="summary"
)
assert mr.model_dump() is not None

# Check 3: ValuationReport with 3 STRONG_BUY and 20 SKIP
strong_buys = [
    DomainDecision(domain_name=f"buy{i}.com", decision="STRONG_BUY")
    for i in range(3)
]
skips = [
    DomainDecision(domain_name=f"skip{i}.com", decision="SKIP")
    for i in range(20)
]
vr = ValuationReport(
    batch_id="batch1",
    strong_buy=strong_buys,
    buy=[],
    maybe=[],
    skip=skips,
)
dump = vr.model_dump_json()
assert "buy0.com" in dump
assert "skip19.com" in dump
print("SUCCESS")
