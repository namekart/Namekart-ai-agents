#!/usr/bin/env python3
"""
Export four aligned CSV files from one pipeline run:

  data/all_domains_report.csv     — every input domain (monitor / audit funnel)
  data/bulk_shortlisted.csv       — domains that passed bulk classifier
  data/linguistic_shortlisted.csv — domains that passed bulk + linguistic gate
  data/pipeline_results.csv       — full ranked output (decisions, scores)

Uses the same input as /trigger (seed_domains.csv or prod MySQL batch).
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import PROJECT_ROOT, settings
from agents.bulk_classifier import run_bulk_classifier
from agents.linguistic_agent import evaluate_linguistic_gate, score_linguistic_deterministic
from agents.scoring import build_linguistic_only_candidates, rank_domains_linguistic_only
from db.connection import SessionLocal
from db.queries import get_todays_domains, resolve_process_date

ALL_DOMAINS_CSV = PROJECT_ROOT / "data" / "all_domains_report.csv"
BULK_CSV = PROJECT_ROOT / "data" / "bulk_shortlisted.csv"
LINGUISTIC_CSV = PROJECT_ROOT / "data" / "linguistic_shortlisted.csv"
PIPELINE_CSV = PROJECT_ROOT / "data" / "pipeline_results.csv"

ALL_DOMAINS_FIELDS = [
    "domain_name",
    "tld",
    "auction_price",
    "process_date",
    "bulk_pass",
    "bulk_score",
    "bulk_reason",
    "ling_pass",
    "ling_score",
    "ling_adjusted",
    "gate_reason",
    "final_stage",
]

BULK_FIELDS = [
    "domain_name",
    "tld",
    "auction_price",
    "process_date",
    "bulk_score",
    "bulk_reason",
]

LINGUISTIC_FIELDS = [
    "domain_name",
    "tld",
    "auction_price",
    "process_date",
    "bulk_score",
    "ling_score",
    "ling_adjusted",
    "gate_reason",
]

PIPELINE_FIELDS = [
    "domain_name",
    "decision",
    "final_score",
    "linguistic_score",
    "bulk_score",
    "valuation_score",
    "gate_passed",
    "gate_detail",
    "auction_price",
    "process_date",
]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _final_stage(bulk_pass: bool, ling_pass: bool) -> str:
    if not bulk_pass:
        return "bulk_rejected"
    if not ling_pass:
        return "linguistic_gated"
    return "linguistic_pass"


def _load_domains(process_date: date | None) -> tuple[list[dict], str]:
    if settings.data_source == "file":
        return get_todays_domains(), "file"

    if not SessionLocal:
        raise SystemExit(
            f"No database session (DATA_SOURCE={settings.data_source!r}). "
            "Set DB_URL_PROD or DB_URL_TEMP in .env."
        )

    with SessionLocal() as session:
        return get_todays_domains(session, process_date=process_date), str(
            resolve_process_date(process_date)
        )


def export_csvs(
    *,
    process_date: date | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    domains, process_date_label = _load_domains(process_date)
    if limit:
        domains = domains[:limit]

    total = len(domains)
    if total == 0:
        raise SystemExit("No input domains found for configured data source / process_date.")

    names = [d["domain_name"].strip().lower() for d in domains]
    meta_by_name = {d["domain_name"].strip().lower(): d for d in domains}

    bulk_results = {r.domain_name: r for r in run_bulk_classifier(names)}

    all_domains_rows: list[dict] = []
    bulk_pass_names: list[str] = []
    linguistic_reports: dict = {}
    ling_pass_rows: list[dict] = []

    for name in names:
        meta = meta_by_name.get(name, {})
        bulk = bulk_results.get(name)
        bulk_pass = bool(bulk and bulk.llm_filter_passed)

        ling_pass = False
        ling_score = ""
        ling_adjusted = ""
        gate_reason = ""

        if bulk_pass:
            bulk_pass_names.append(name)
            report = score_linguistic_deterministic(name)
            linguistic_reports[name] = report
            ling_pass, ling_adjusted_val, gate_reason = evaluate_linguistic_gate(report)
            ling_score = report.overall_linguistic_score
            ling_adjusted = ling_adjusted_val

            if ling_pass:
                ling_pass_rows.append({
                    "domain_name": name,
                    "tld": meta.get("tld") or (name.rsplit(".", 1)[-1] if "." in name else "com"),
                    "auction_price": meta.get("auction_price", 0),
                    "process_date": process_date_label,
                    "bulk_score": bulk.brandability_score,
                    "ling_score": ling_score,
                    "ling_adjusted": ling_adjusted,
                    "gate_reason": gate_reason or "",
                })

        all_domains_rows.append({
            "domain_name": name,
            "tld": meta.get("tld") or (name.rsplit(".", 1)[-1] if "." in name else "com"),
            "auction_price": meta.get("auction_price", 0),
            "process_date": process_date_label,
            "bulk_pass": bulk_pass,
            "bulk_score": bulk.brandability_score if bulk else "",
            "bulk_reason": bulk.llm_filter_reason if bulk else "missing",
            "ling_pass": ling_pass if bulk_pass else False,
            "ling_score": ling_score,
            "ling_adjusted": ling_adjusted,
            "gate_reason": gate_reason if bulk_pass else "skipped_bulk",
            "final_stage": _final_stage(bulk_pass, ling_pass if bulk_pass else False),
        })

    bulk_rows = []
    for name in bulk_pass_names:
        meta = meta_by_name.get(name, {})
        bulk = bulk_results[name]
        bulk_rows.append({
            "domain_name": name,
            "tld": meta.get("tld") or (name.rsplit(".", 1)[-1] if "." in name else "com"),
            "auction_price": meta.get("auction_price", 0),
            "process_date": process_date_label,
            "bulk_score": bulk.brandability_score,
            "bulk_reason": bulk.llm_filter_reason,
        })

    filtered_domains = [meta_by_name[n] for n in bulk_pass_names]
    candidates = build_linguistic_only_candidates(
        filtered_domains,
        linguistic_reports,
        bulk_results,
    )
    ranked = rank_domains_linguistic_only(candidates)
    pipeline_rows = [
        {
            "domain_name": r["domain_name"],
            "decision": r["decision"],
            "final_score": r["final_score"],
            "linguistic_score": r["linguistic_score"],
            "bulk_score": r.get("bulk_score", ""),
            "valuation_score": r.get("valuation_score", ""),
            "gate_passed": r.get("gate_passed", False),
            "gate_detail": r.get("gate_detail", ""),
            "auction_price": r.get("auction_price", 0),
            "process_date": process_date_label,
        }
        for r in ranked
    ]

    _write_csv(ALL_DOMAINS_CSV, ALL_DOMAINS_FIELDS, all_domains_rows)
    _write_csv(BULK_CSV, BULK_FIELDS, bulk_rows)
    _write_csv(LINGUISTIC_CSV, LINGUISTIC_FIELDS, ling_pass_rows)
    _write_csv(PIPELINE_CSV, PIPELINE_FIELDS, pipeline_rows)

    counts = {
        "input": total,
        "all_domains": len(all_domains_rows),
        "bulk_shortlisted": len(bulk_rows),
        "linguistic_shortlisted": len(ling_pass_rows),
        "pipeline_results": len(pipeline_rows),
        "strong_buy": sum(1 for r in pipeline_rows if r["decision"] == "STRONG_BUY"),
        "buy": sum(1 for r in pipeline_rows if r["decision"] == "BUY"),
        "maybe": sum(1 for r in pipeline_rows if r["decision"] == "MAYBE"),
        "skip": sum(1 for r in pipeline_rows if r["decision"] == "SKIP"),
    }
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Export bulk, linguistic, and pipeline CSVs")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Override process_date YYYY-MM-DD (prod/temp only)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit input domains (testing)")
    args = parser.parse_args()

    process_date = date.fromisoformat(args.date) if args.date else None
    counts = export_csvs(process_date=process_date, limit=args.limit)

    print(
        f"Input: {counts['input']}  |  "
        f"DATA_SOURCE={settings.data_source}  |  "
        f"process_date={resolve_process_date(process_date)}"
    )
    print(f"All domains (audit):    {counts['all_domains']:6}  -> {ALL_DOMAINS_CSV}")
    print(f"Bulk shortlisted:       {counts['bulk_shortlisted']:6}  -> {BULK_CSV}")
    print(f"Linguistic shortlisted: {counts['linguistic_shortlisted']:6}  -> {LINGUISTIC_CSV}")
    print(f"Pipeline results:       {counts['pipeline_results']:6}  -> {PIPELINE_CSV}")
    print(
        f"Decisions: STRONG_BUY={counts['strong_buy']}  BUY={counts['buy']}  "
        f"MAYBE={counts['maybe']}  SKIP={counts['skip']}"
    )


if __name__ == "__main__":
    main()
