"""Quality checks for .ai acquisition domains (user-reported false negatives)."""

from agents.linguistic_agent import evaluate_linguistic_gate, score_linguistic_deterministic
from agents.scoring import (
    assign_linguistic_decision,
    build_linguistic_only_candidates,
    rank_domains_linguistic_only,
)
from agents.domain_quality import passes_bulk_filter


STRONG_BUY_EXPECTED = ["leadteam.ai", "neuralbank.ai", "unbuild.ai"]
SHOULD_NOT_SKIP = ["tridev.ai", "neoteams.ai", "myloop.ai"]


def _row(domain: str, price: float = 80.0) -> dict:
    passed, bulk_score, _ = passes_bulk_filter(domain)
    assert passed, f"{domain} should pass bulk"
    ling = score_linguistic_deterministic(domain)
    gate_ok, _, _ = evaluate_linguistic_gate(ling)
    candidates = build_linguistic_only_candidates(
        [{"domain_name": domain, "auction_price": price, "auction_bidders": 1}],
        {domain: ling},
        {domain: type("B", (), {"brandability_score": bulk_score})()},
    )
    return rank_domains_linguistic_only(candidates)[0]


def test_premium_ai_domains_strong_buy():
    for domain in STRONG_BUY_EXPECTED:
        result = _row(domain)
        assert result["gate_passed"], domain
        assert result["decision"] in ("STRONG_BUY", "BUY"), (
            f"{domain}: expected STRONG_BUY/BUY, got {result['decision']} "
            f"(ling={result['linguistic_score']}, bulk={result['bulk_score']})"
        )


def test_borderline_ai_domains_not_skip():
    for domain in SHOULD_NOT_SKIP:
        result = _row(domain)
        assert result["gate_passed"], f"{domain} failed gate"
        assert result["decision"] in ("STRONG_BUY", "BUY", "MAYBE"), (
            f"{domain}: expected pass tier, got {result['decision']}"
        )


def test_junk_still_skip():
    result = assign_linguistic_decision({
        "domain_name": "zzzeze.xyz",
        "gate_passed": False,
        "linguistic_score": 2.0,
        "bulk_score": 1,
    })
    assert result == "SKIP"
