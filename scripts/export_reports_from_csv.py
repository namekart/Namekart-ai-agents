#!/usr/bin/env python3
"""Run bulk+linguistic pipeline from any CSV and export all stage reports."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))
sys.path.insert(0, str(ROOT / "schemas"))

from agents.bulk_classifier import run_bulk_classifier
from agents.linguistic_agent import (
    evaluate_linguistic_gate,
    run_linguistic_agent_batch,
    score_linguistic_deterministic,
)
from agents.scoring import build_linguistic_only_candidates, rank_domains_linguistic_only

ALL_FIELDS = [
    "domain_name",
    "tld",
    "auction_price",
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
    "bulk_score",
    "bulk_reason",
]

LING_FIELDS = [
    "domain_name",
    "tld",
    "auction_price",
    "bulk_score",
    "ling_score",
    "ling_adjusted",
    "gate_reason",
]

PIPE_FIELDS = [
    "domain_name",
    "decision",
    "final_score",
    "linguistic_score",
    "bulk_score",
    "valuation_score",
    "gate_passed",
    "gate_detail",
    "auction_price",
]


def _read_domains(csv_path: Path, limit: int | None = None) -> list[dict]:
    with open(csv_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if limit:
        rows = rows[:limit]

    domains: list[dict] = []
    for row in rows:
        name = (row.get("domain_name") or row.get("domain") or "").strip().lower()
        if not name:
            continue
        tld = (row.get("tld") or (name.rsplit(".", 1)[-1] if "." in name else "com")).strip().lower()
        try:
            auction_price = float(row.get("auction_price", 0) or 0)
        except ValueError:
            auction_price = 0.0
        try:
            auction_bidders = int(float(row.get("auction_bidders", 0) or 0))
        except ValueError:
            auction_bidders = 0
        domains.append(
            {
                "domain_name": name,
                "tld": tld,
                "auction_price": auction_price,
                "auction_bidders": auction_bidders,
            }
        )
    return domains


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _final_stage(bulk_pass: bool, ling_pass: bool) -> str:
    if not bulk_pass:
        return "bulk_rejected"
    if not ling_pass:
        return "linguistic_gated"
    return "linguistic_pass"


def run_export(
    input_csv: Path,
    output_dir: Path,
    limit: int | None = None,
    ling_batch_size: int = 50,
) -> dict[str, int]:
    domains = _read_domains(input_csv, limit=limit)
    if not domains:
        raise SystemExit("No valid domains found in input CSV.")

    names = [d["domain_name"] for d in domains]
    by_name = {d["domain_name"]: d for d in domains}
    bulk_results = {r.domain_name: r for r in run_bulk_classifier(names)}

    all_rows: list[dict] = []
    bulk_rows: list[dict] = []
    ling_rows: list[dict] = []
    linguistic_reports: dict = {}
    bulk_pass_names: list[str] = []

    for name in names:
        meta = by_name[name]
        bulk = bulk_results.get(name)
        bulk_pass = bool(bulk and bulk.llm_filter_passed)
        if bulk_pass:
            bulk_pass_names.append(name)
            bulk_rows.append(
                {
                    "domain_name": name,
                    "tld": meta["tld"],
                    "auction_price": meta["auction_price"],
                    "bulk_score": bulk.brandability_score,
                    "bulk_reason": bulk.llm_filter_reason,
                }
            )

    # Linguistic scoring on bulk-pass set (LLM path if enabled, deterministic otherwise).
    if bulk_pass_names:
        for i in range(0, len(bulk_pass_names), max(1, int(ling_batch_size))):
            sub_domains = bulk_pass_names[i : i + ling_batch_size]
            reports = run_linguistic_agent_batch(sub_domains)
            for r in reports:
                linguistic_reports[r.domain_name.strip().lower()] = r
        for name in bulk_pass_names:
            if name not in linguistic_reports:
                linguistic_reports[name] = score_linguistic_deterministic(name)

    for name in names:
        meta = by_name[name]
        bulk = bulk_results.get(name)
        bulk_pass = bool(bulk and bulk.llm_filter_passed)
        ling_pass = False
        ling_score = ""
        ling_adjusted = ""
        gate_reason = ""

        if bulk_pass:
            report = linguistic_reports.get(name)
            if report:
                ling_pass, ling_adjusted_val, gate_reason = evaluate_linguistic_gate(report)
                ling_score = report.overall_linguistic_score
                ling_adjusted = ling_adjusted_val
                if ling_pass:
                    ling_rows.append(
                        {
                            "domain_name": name,
                            "tld": meta["tld"],
                            "auction_price": meta["auction_price"],
                            "bulk_score": bulk.brandability_score,
                            "ling_score": ling_score,
                            "ling_adjusted": ling_adjusted,
                            "gate_reason": gate_reason or "",
                        }
                    )

        all_rows.append(
            {
                "domain_name": name,
                "tld": meta["tld"],
                "auction_price": meta["auction_price"],
                "bulk_pass": bulk_pass,
                "bulk_score": bulk.brandability_score if bulk else "",
                "bulk_reason": bulk.llm_filter_reason if bulk else "missing",
                "ling_pass": ling_pass if bulk_pass else False,
                "ling_score": ling_score,
                "ling_adjusted": ling_adjusted,
                "gate_reason": gate_reason if bulk_pass else "skipped_bulk",
                "final_stage": _final_stage(bulk_pass, ling_pass if bulk_pass else False),
            }
        )

    candidates = build_linguistic_only_candidates(
        [by_name[n] for n in bulk_pass_names],
        linguistic_reports,
        bulk_results,
    )
    ranked = rank_domains_linguistic_only(candidates)
    pipe_rows = [
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
        }
        for r in ranked
    ]

    _write_csv(output_dir / "all_domains_report.csv", ALL_FIELDS, all_rows)
    _write_csv(output_dir / "bulk_shortlisted.csv", BULK_FIELDS, bulk_rows)
    _write_csv(output_dir / "linguistic_shortlisted.csv", LING_FIELDS, ling_rows)
    _write_csv(output_dir / "pipeline_results.csv", PIPE_FIELDS, pipe_rows)

    return {
        "input": len(domains),
        "bulk_shortlisted": len(bulk_rows),
        "linguistic_shortlisted": len(ling_rows),
        "pipeline_results": len(pipe_rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export reports from a source CSV")
    parser.add_argument("input_csv", help="Path to source CSV (must include domain or domain_name)")
    parser.add_argument("--outdir", required=True, help="Output directory for report files")
    parser.add_argument("--limit", type=int, default=None, help="Optional input limit")
    parser.add_argument(
        "--ling-batch-size",
        type=int,
        default=50,
        help="Batch size for linguistic scoring requests in this runner",
    )
    args = parser.parse_args()

    input_csv = Path(args.input_csv)
    outdir = Path(args.outdir)
    counts = run_export(input_csv, outdir, limit=args.limit, ling_batch_size=args.ling_batch_size)
    print(f"Input domains:          {counts['input']}")
    print(f"Bulk shortlisted:       {counts['bulk_shortlisted']}")
    print(f"Linguistic shortlisted: {counts['linguistic_shortlisted']}")
    print(f"Pipeline results:       {counts['pipeline_results']}")
    print(f"Report folder:          {outdir}")


if __name__ == "__main__":
    main()

