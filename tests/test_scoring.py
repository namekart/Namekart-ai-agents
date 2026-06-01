"""Tests for unified ranking — scores must not cluster artificially."""


def test_valuation_score_varies_by_domain():
    from agents.scoring import valuation_display_score

    cheap_com = valuation_display_score(
        {"domain_name": "growhub.net", "auction_price": 55, "auction_bidders": 2},
        linguistic_score=8.0,
    )
    expensive_ai = valuation_display_score(
        {"domain_name": "algowise.ai", "auction_price": 2500, "auction_bidders": 0},
        linguistic_score=7.5,
    )
    assert cheap_com > expensive_ai
    assert expensive_ai != cheap_com


def test_ai_coined_names_score_lower_linguistic():
    from agents.linguistic_agent import score_linguistic_deterministic

    premium = score_linguistic_deterministic("therapist.com")
    coined = score_linguistic_deterministic("algowise.ai")
    assert premium.overall_linguistic_score > coined.overall_linguistic_score


def test_rank_domains_spread_decisions():
    from agents.scoring import rank_domains

    candidates = [
        {"domain_name": "a.com", "final_score": 8.5, "linguistic_score": 8.0, "market_score": 8.0, "market_report": {"market_exists": True}},
        {"domain_name": "b.com", "final_score": 6.0, "linguistic_score": 6.5, "market_score": 6.0, "market_report": {"market_exists": True}},
        {"domain_name": "c.com", "final_score": 3.5, "linguistic_score": 4.0, "market_score": 3.0, "market_report": {"market_exists": False}},
    ]
    ranked = rank_domains(candidates, strong_buy_pct=0.34, buy_pct=0.34)
    decisions = {r["domain_name"]: r["decision"] for r in ranked}
    assert decisions["a.com"] == "STRONG_BUY"
    assert decisions["c.com"] in ("MAYBE", "SKIP")


def test_market_score_not_only_three_values():
    from agents.scoring import market_display_score

    scores = {
        market_display_score({"market_trajectory": "growing", "market_exists": True, "funding_activity": "comparable domains confidence High"}),
        market_display_score({"market_trajectory": "unknown", "market_exists": False, "needs_manual_review": True}),
        market_display_score({"market_trajectory": "stable", "market_exists": True, "funding_activity": "some funding raised"}),
    }
    assert len(set(scores)) >= 2
