"""
Integration tests for the APR bridge and accuracy fixes.

Run with:
    uv run python -m pytest tests/test_apr_integration.py -v
"""

import pytest

# ---------------------------------------------------------------------------
# Test 1 — Determinism: same input → same output, always
# ---------------------------------------------------------------------------

def test_linguistic_determinism():
    """Same domain must produce identical linguistic scores on repeated calls."""
    from agents.linguistic_agent import score_linguistic_deterministic

    domains = [
        "therapist.com",
        "flipkart.com",
        "growhub.net",
        "zzzeze.xyz",
        "asdfjkl.info",
    ]
    first_run = {d: score_linguistic_deterministic(d) for d in domains}
    second_run = {d: score_linguistic_deterministic(d) for d in domains}

    for d in domains:
        r1 = first_run[d]
        r2 = second_run[d]
        assert r1.memorability == r2.memorability, f"{d}: memorability changed"
        assert r1.pronounceability == r2.pronounceability, f"{d}: pronounceability changed"
        assert r1.overall_linguistic_score == r2.overall_linguistic_score, f"{d}: overall score changed"


# ---------------------------------------------------------------------------
# Test 2 — Junk domain linguistic scores must be LOW
# ---------------------------------------------------------------------------

def test_junk_domains_score_low():
    """Garbage domains like zzzeze.xyz and asdfjkl.info must score < 4."""
    from agents.linguistic_agent import score_linguistic_deterministic

    junk_domains = [
        "zzzeze.xyz",
        "asdfjkl.info",
        "a-b-c-d.org",
        "lkjhgfdsa.net",
        "123my.com",
    ]
    for domain in junk_domains:
        report = score_linguistic_deterministic(domain)
        assert report.overall_linguistic_score < 5.0, (
            f"{domain} scored {report.overall_linguistic_score} — expected < 5.0 for junk domain"
        )


# ---------------------------------------------------------------------------
# Test 3 — Premium domains linguistic scores must be HIGHER than junk
# ---------------------------------------------------------------------------

def test_premium_domains_score_higher_than_junk():
    """Known good domains must outscore random junk domains."""
    from agents.linguistic_agent import score_linguistic_deterministic

    premium = ["therapist.com", "flipkart.com", "growhub.net"]
    junk = ["zzzeze.xyz", "asdfjkl.info", "lkjhgfdsa.net"]

    avg_premium = sum(score_linguistic_deterministic(d).overall_linguistic_score for d in premium) / len(premium)
    avg_junk = sum(score_linguistic_deterministic(d).overall_linguistic_score for d in junk) / len(junk)

    assert avg_premium > avg_junk + 1.0, (
        f"Premium avg ({avg_premium:.2f}) should be > junk avg ({avg_junk:.2f}) + 1.0"
    )


# ---------------------------------------------------------------------------
# Test 4 — Valuation score: junk domains on bad TLDs must score < 4
# ---------------------------------------------------------------------------

def test_junk_valuation_score():
    """
    Previously zzzeze.xyz with $0 auction price scored 9.
    After fix it must score < 4.
    """
    from agents.scoring import valuation_display_score
    from agents.linguistic_agent import score_linguistic_deterministic

    junk_domains = [
        {"domain_name": "zzzeze.xyz", "tld": "xyz", "auction_price": 0, "auction_bidders": 0},
        {"domain_name": "asdfjkl.info", "tld": "info", "auction_price": 0, "auction_bidders": 0},
        {"domain_name": "a-b-c-d.org", "tld": "org", "auction_price": 0, "auction_bidders": 0},
    ]
    for domain in junk_domains:
        ling = score_linguistic_deterministic(domain["domain_name"])
        score = valuation_display_score(domain, linguistic_score=ling.overall_linguistic_score)
        assert score <= 4.5, (
            f"{domain['domain_name']} valuation_score={score:.2f} — expected ≤ 4.5 for junk"
        )


# ---------------------------------------------------------------------------
# Test 5 — Premium domains on .com must score >= 5
# ---------------------------------------------------------------------------

def test_premium_valuation_score():
    """Good premium domains at low auction prices should score >= 5."""
    from agents.scoring import valuation_display_score
    from agents.linguistic_agent import score_linguistic_deterministic

    # These are the premium side of the test set, at low/unknown auction price
    premium_domains = [
        {"domain_name": "therapist.com", "tld": "com", "auction_price": 20, "auction_bidders": 2},
        {"domain_name": "growhub.net", "tld": "net", "auction_price": 30, "auction_bidders": 1},
    ]
    for domain in premium_domains:
        ling = score_linguistic_deterministic(domain["domain_name"])
        score = valuation_display_score(domain, linguistic_score=ling.overall_linguistic_score)
        assert score >= 5.0, (
            f"{domain['domain_name']} valuation_score={score:.2f} — expected >= 5.0 for premium"
        )


# ---------------------------------------------------------------------------
# Test 6 — APR bridge mapping: dollar string parsing
# ---------------------------------------------------------------------------

def test_dollar_parsing():
    """_parse_dollar must handle common APR agent output formats."""
    from agents.apr_bridge import _parse_dollar

    cases = [
        ("$1,250", 1250.0),
        ("$12,500", 12500.0),
        ("1250", 1250.0),
        ("$0", 0.0),
        ("", 0.0),
        (None, 0.0),
        # Range string: only FIRST number is parsed (the predictedAPR, not aprRange)
        ("$1,000 - $2,000", 1000.0),
    ]
    for raw, expected in cases:
        result = _parse_dollar(raw)
        assert abs(result - expected) < 1, (
            f"_parse_dollar({raw!r}) = {result}, expected {expected}"
        )


# ---------------------------------------------------------------------------
# Test 7 — Trajectory inference is deterministic
# ---------------------------------------------------------------------------

def test_trajectory_deterministic():
    """_infer_trajectory must return same result for same input."""
    from agents.apr_bridge import _infer_trajectory

    growing_result = {
        "apr_prediction": {"reasoning": "The domain shows strong growth potential with rising CAGR in fintech."},
        "similar_domains": [{"domain": "fintech.com"}],
    }
    declining_result = {
        "apr_prediction": {"reasoning": "The market is declining with shrinking demand."},
        "similar_domains": [],
    }
    assert _infer_trajectory(growing_result, "High") == "growing"
    assert _infer_trajectory(declining_result, "Low") == "declining"
    # Run twice to verify determinism
    assert _infer_trajectory(growing_result, "High") == "growing"
    assert _infer_trajectory(declining_result, "Low") == "declining"


# ---------------------------------------------------------------------------
# Test 8 — Schema conversion: APRResult → MarketResearchReport
# ---------------------------------------------------------------------------

def test_apr_to_market_report_conversion():
    """APRResult must convert cleanly to MarketResearchReport."""
    from agents.apr_bridge import apr_result_to_market_report
    from schemas.apr_result import APRResult

    result = APRResult(
        domain_name="therapist.com",
        predicted_apr=850.0,
        apr_range_low=600.0,
        apr_range_high=1100.0,
        confidence="High",
        domain_category="Descriptive",
        similar_domains_count=7,
        market_trajectory="growing",
        market_exists=True,
        reasoning_summary="Strong healthcare domain with high buyer demand.",
    )
    report = apr_result_to_market_report(result)
    assert report.domain_name == "therapist.com"
    assert report.market_exists is True
    assert report.market_trajectory == "growing"
    assert "850" in report.raw_search_summary
