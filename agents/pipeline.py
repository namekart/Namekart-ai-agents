import uuid
import time
from typing import TypedDict

import structlog
from langgraph.graph import StateGraph, START, END

from agents.bulk_classifier import run_bulk_classifier
from agents.linguistic_agent import run_linguistic_agent_batch, evaluate_linguistic_gate
from app.config import settings

logger = structlog.get_logger()


class PipelineState(TypedDict):
    raw_domains: list[dict]
    filtered_domains: list[dict]
    batches: list[list[dict]]
    bulk_reports: dict  # domain_name -> BulkClassifier result
    linguistic_reports: dict
    skipped_domains: list[dict]
    errors: list[str]


def node_bulk_classifier(state: PipelineState) -> dict:
    """Stage 1: bulk classifier — filter junk domains (local heuristics by default)."""
    raw = state.get("raw_domains", [])
    if not raw:
        return {"filtered_domains": [], "batches": [], "bulk_reports": {}}

    domain_names = [d["domain_name"].strip().lower() for d in raw]

    try:
        bulk_results = run_bulk_classifier(domain_names)
    except Exception as e:
        return {"errors": [f"Bulk classifier failed: {str(e)}"]}

    bulk_by_name = {r.domain_name: r for r in bulk_results}
    passed_names = {name for name, result in bulk_by_name.items() if result.llm_filter_passed}
    filtered_domains = [
        d for d in raw if d["domain_name"].strip().lower() in passed_names
    ]
    skipped_domains = list(state.get("skipped_domains", []))
    for domain in raw:
        name = domain["domain_name"].strip().lower()
        if name not in passed_names:
            result = bulk_by_name.get(name)
            skipped_domains.append({
                "domain_name": name,
                "reason": "bulk_filter",
                "linguistic_score": None,
                "bulk_score": getattr(result, "brandability_score", None),
            })

    batch_size = settings.pipeline_batch_size
    batches = [
        filtered_domains[i : i + batch_size]
        for i in range(0, len(filtered_domains), batch_size)
    ]

    logger.info(
        "Bulk classifier done",
        total=len(raw),
        passed=len(filtered_domains),
        batches=len(batches),
    )

    return {
        "filtered_domains": filtered_domains,
        "batches": batches,
        "bulk_reports": bulk_by_name,
        "skipped_domains": skipped_domains,
    }


def node_process_batches(state: PipelineState) -> dict:
    """Stage 2: linguistic agent + gate (no APR, ChromaDB, or market research)."""
    batches = state.get("batches", [])
    bulk_reports = state.get("bulk_reports", {})

    all_ling_reports: dict = {}
    skipped_domains: list = list(state.get("skipped_domains", []))
    errors: list = list(state.get("errors", []))

    for batch in batches:
        batch_id = str(uuid.uuid4())
        domain_names = [d["domain_name"].strip().lower() for d in batch]

        ling_batch_size = settings.linguistic_batch_size
        for i in range(0, len(domain_names), ling_batch_size):
            sub_domains = domain_names[i : i + ling_batch_size]
            try:
                reports = run_linguistic_agent_batch(sub_domains)
                for r in reports:
                    all_ling_reports[r.domain_name.strip().lower()] = r
            except Exception as e:
                errors.append(f"Linguistic batch failed: {e}")

            if i + ling_batch_size < len(domain_names):
                time.sleep(settings.request_delay_seconds)

        logger.info(
            "Linguistic stage done",
            batch_id=batch_id,
            analysed=len([n for n in domain_names if n in all_ling_reports]),
        )

        for d in batch:
            name = d["domain_name"].strip().lower()
            ling = all_ling_reports.get(name)
            if not ling:
                skipped_domains.append({
                    "domain_name": name,
                    "reason": "linguistic_missing",
                    "linguistic_score": None,
                })
                continue

            gate_passed, adjusted_score, fail_reason = evaluate_linguistic_gate(ling)
            if not gate_passed:
                skipped_domains.append({
                    "domain_name": name,
                    "reason": "linguistic_gate",
                    "linguistic_score": adjusted_score,
                    "gate_detail": fail_reason,
                })

        gate_passed_count = sum(
            1
            for n in domain_names
            if (ling := all_ling_reports.get(n))
            and evaluate_linguistic_gate(ling)[0]
        )
        logger.info(
            "Linguistic gate applied",
            batch_id=batch_id,
            passed=gate_passed_count,
            gated=len(domain_names) - gate_passed_count,
        )

    return {
        "linguistic_reports": all_ling_reports,
        "bulk_reports": bulk_reports,
        "skipped_domains": skipped_domains,
        "errors": errors,
    }


def build_graph():
    workflow = StateGraph(PipelineState)

    workflow.add_node("bulk_classifier", node_bulk_classifier)
    workflow.add_node("process_batches", node_process_batches)

    workflow.add_edge(START, "bulk_classifier")
    workflow.add_edge("bulk_classifier", "process_batches")
    workflow.add_edge("process_batches", END)

    return workflow.compile()


graph = build_graph()
