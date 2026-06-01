"""
Tests for strict bulk + linguistic filtering (quality over quantity).
"""

from agents.bulk_classifier import run_bulk_classifier
from agents.domain_quality import passes_bulk_filter
from agents.linguistic_agent import evaluate_linguistic_gate, score_linguistic_deterministic


# ── Bulk: junk must fail ────────────────────────────────────────────────────

JUNK_BULK = [
    "zzzeze.xyz",
    "asdfjkl.info",
    "lkjhgfdsa.net",
    "123my.com",
    "a-b-c-d.org",
    "bestinsurancequotes.online",
    "randomxzqtfp.com",
    "clickwin.top",
]

PREMIUM_BULK = [
    "therapist.com",
    "growhub.net",
    "payflow.io",
    "codenest.ai",
    "hirebase.co",
]


def test_junk_domains_fail_bulk():
    for domain in JUNK_BULK:
        passed, score, _ = passes_bulk_filter(domain)
        assert not passed, f"{domain} should fail bulk (score={score})"


def test_premium_domains_pass_bulk():
    for domain in PREMIUM_BULK:
        passed, score, reason = passes_bulk_filter(domain)
        assert passed, f"{domain} should pass bulk (score={score}, reason={reason})"


def test_bulk_classifier_batch_strict():
    mixed = JUNK_BULK + PREMIUM_BULK
    results = run_bulk_classifier(mixed)
    by_name = {r.domain_name: r for r in results}

    for domain in JUNK_BULK:
        assert not by_name[domain.strip().lower()].llm_filter_passed, domain

    passed_premium = sum(
        1 for d in PREMIUM_BULK if by_name[d.strip().lower()].llm_filter_passed
    )
    assert passed_premium >= len(PREMIUM_BULK) - 1, "Most premium domains should pass bulk"


# ── Linguistic gate: multi-criteria ─────────────────────────────────────────

def test_junk_fails_linguistic_gate():
    for domain in JUNK_BULK:
        report = score_linguistic_deterministic(domain)
        passed, adjusted, reason = evaluate_linguistic_gate(report)
        assert not passed, f"{domain} should fail linguistic gate ({adjusted}, {reason})"


def test_premium_passes_linguistic_gate():
    passed_count = 0
    for domain in PREMIUM_BULK:
        report = score_linguistic_deterministic(domain)
        passed, adjusted, reason = evaluate_linguistic_gate(report)
        if passed:
            passed_count += 1
        else:
            print(f"  {domain}: {adjusted}, {reason}")
    assert passed_count >= len(PREMIUM_BULK) - 1, "Most premium domains should pass linguistic gate"


def test_weak_tld_blocked_at_linguistic():
    """Even decent stems on .info should fail when linguistic_block_weak_tlds=True."""
    report = score_linguistic_deterministic("brightpath.info")
    passed, _, reason = evaluate_linguistic_gate(report)
    assert not passed
    assert "weak tld" in reason


def test_simulated_pipeline_funnel():
    """
    Simulate 50k-style mix: mostly junk keyword + random domains.
    Pass rate should stay low (quality > quantity).
    Linguistic must reject a meaningful share of bulk survivors.
    """
    synthetic_junk = [
        f"keyword{i}insurance.com" for i in range(40)
    ] + [
        f"asdf{i}.xyz" for i in range(30)
    ] + [
        f"cityname{i}lawyer.net" for i in range(30)
    ]
    synthetic_mediocre = [
        "daffasindo.com",
        "lookangel.com",
        "dwomo.com",
        "aolimo.com",
        "konchak.com",
    ]
    synthetic_good = PREMIUM_BULK + [
        "medsync.net",
    ] + synthetic_mediocre

    pool = synthetic_junk + synthetic_good
    bulk_pass = run_bulk_classifier(pool)
    bulk_passed = [r for r in bulk_pass if r.llm_filter_passed]

    ling_pass = 0
    for r in bulk_passed:
        report = score_linguistic_deterministic(r.domain_name)
        passed, _, _ = evaluate_linguistic_gate(report)
        if passed:
            ling_pass += 1

    bulk_rate = len(bulk_passed) / len(pool)
    ling_rate = ling_pass / len(pool)
    bulk_to_ling_rate = ling_pass / max(len(bulk_passed), 1)

    assert bulk_rate < 0.25, f"Bulk pass rate too high: {bulk_rate:.1%}"
    assert ling_rate < 0.10, f"Linguistic pass rate too high: {ling_rate:.1%}"
    assert ling_pass <= 15, f"Too many domains passed linguistic gate: {ling_pass}"
    assert bulk_to_ling_rate < 0.85, (
        f"Linguistic gate too lenient on bulk survivors: {bulk_to_ling_rate:.1%}"
    )
