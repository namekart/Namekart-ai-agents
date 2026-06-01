from typing import Iterable

from app.config import settings
from agents.domain_quality import passes_bulk_filter
from agents.llm_client import make_instructor_client
from prompts.bulk_classifier import BULK_CLASSIFIER_SYSTEM, BULK_CLASSIFIER_USER
from schemas.bulk_filter import BulkFilterResult

client = make_instructor_client()


def run_bulk_classifier(domains: list[str]) -> list[BulkFilterResult]:
    """
    Stage-1 filter: LLM-first brandability screening.

    Deterministic heuristics remain only as a resilience fallback if the LLM call
    fails or settings disable LLM usage.
    """
    if settings.enforce_deterministic_pipeline:
        return _heuristic_bulk_results(domains)

    if settings.use_llm_bulk_classifier:
        llm_results = _llm_bulk_results(domains)
        if llm_results:
            return llm_results

    return _heuristic_bulk_results(domains)


def _llm_bulk_results(domains: list[str]) -> list[BulkFilterResult]:
    all_results: list[BulkFilterResult] = []
    batch_size = max(1, int(settings.bulk_llm_batch_size))
    normalized_domains = [d.strip().lower() for d in domains if d and d.strip()]
    batches = [
        normalized_domains[i:i + batch_size]
        for i in range(0, len(normalized_domains), batch_size)
    ]

    for batch in batches:
        domain_list_str = "\n".join(f"- {d}" for d in batch)
        messages = [
            {"role": "system", "content": BULK_CLASSIFIER_SYSTEM},
            {"role": "user", "content": BULK_CLASSIFIER_USER.format(domain_list=domain_list_str)},
        ]
        try:
            batch_results = client.chat.completions.create(
                model=settings.model_fast,
                response_model=Iterable[BulkFilterResult],
                messages=messages,
                max_retries=3,
            )
            for result in batch_results:
                normalized = result.domain_name.strip().lower()
                # Keep LLM decision as source of truth for bulk pass/fail.
                score = max(1, min(10, int(result.brandability_score)))
                all_results.append(BulkFilterResult(
                    domain_name=normalized,
                    brandability_score=score,
                    llm_filter_passed=bool(result.llm_filter_passed),
                    # Keep bulk output compact to control tokens/storage.
                    llm_filter_reason="",
                ))
        except Exception as exc:
            print(f"Error processing batch of domains: {exc}")
            all_results.extend(_heuristic_bulk_results(batch))

    # Ensure every requested domain gets a result even if model omits some.
    by_name = {r.domain_name: r for r in all_results}
    for name in normalized_domains:
        if name not in by_name:
            by_name[name] = _heuristic_bulk_result(name)

    all_results = [by_name[name] for name in normalized_domains]
    return all_results


def _heuristic_bulk_results(domains: list[str]) -> list[BulkFilterResult]:
    return [_heuristic_bulk_result(domain) for domain in domains]


def _heuristic_bulk_result(domain_name: str) -> BulkFilterResult:
    normalized = domain_name.strip().lower()
    passed, score, _reason = passes_bulk_filter(normalized)
    return BulkFilterResult(
        domain_name=normalized,
        brandability_score=score,
        llm_filter_passed=passed,
        # Do not carry verbose rule text in pipeline artifacts.
        llm_filter_reason="",
    )
