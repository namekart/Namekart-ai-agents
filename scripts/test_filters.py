#!/usr/bin/env python3
"""Quick filter funnel test — bulk + linguistic only, optional CSV export."""

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
from db.connection import SessionLocal
from db.queries import get_todays_domains, resolve_process_date

DEFAULT_CSV = PROJECT_ROOT / "data" / "all_domains_report.csv"

SAMPLE_DOMAINS = [
    "therapist.com",
    "growhub.net",
    "flipkart.com",
    "notion.io",
    "zzzeze.xyz",
    "asdfjkl.info",
    "bestinsurancequotes.online",
    "randomxzqtfp.com",
]

CSV_FIELDS = [
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


def run_sample() -> None:
    print("=== SAMPLE DOMAINS ===\n")
    print(f"{'DOMAIN':35} {'BULK':6} {'SCORE':5}  BULK REASON")
    print("-" * 80)
    for r in run_bulk_classifier(SAMPLE_DOMAINS):
        print(f"{r.domain_name:35} {str(r.llm_filter_passed):6} {r.brandability_score:5}  {r.llm_filter_reason}")

    print(f"\n{'DOMAIN':35} {'PASS':6} {'ADJ':5}  GATE REASON")
    print("-" * 80)
    for d in SAMPLE_DOMAINS:
        report = score_linguistic_deterministic(d)
        passed, adj, reason = evaluate_linguistic_gate(report)
        print(f"{d:35} {str(passed):6} {adj:5.1f}  {reason or 'ok'}")


def _load_domains(process_date: date | None) -> tuple[list[dict], str]:
    """Load input domains the same way scheduled_job does (DB session required for prod/temp)."""
    if settings.data_source == "file":
        return get_todays_domains(), "file"

    if not SessionLocal:
        print(
            f"No database session (DATA_SOURCE={settings.data_source!r}). "
            "Set DB_URL_PROD or DB_URL_TEMP in .env."
        )
        return [], str(resolve_process_date(process_date))

    with SessionLocal() as session:
        return get_todays_domains(session, process_date=process_date), str(
            resolve_process_date(process_date)
        )


def _final_stage(bulk_pass: bool, ling_pass: bool) -> str:
    if not bulk_pass:
        return "bulk_rejected"
    if not ling_pass:
        return "linguistic_gated"
    return "linguistic_pass"


def build_report_rows(
    domains: list[dict],
    process_date_label: str,
) -> list[dict]:
    names = [d["domain_name"] for d in domains]
    domain_by_name = {d["domain_name"].strip().lower(): d for d in domains}
    bulk_results = {r.domain_name: r for r in run_bulk_classifier(names)}

    rows: list[dict] = []
    for name in names:
        key = name.strip().lower()
        meta = domain_by_name.get(key, {})
        bulk = bulk_results.get(key)
        bulk_pass = bool(bulk and bulk.llm_filter_passed)

        ling_pass = False
        ling_score = ""
        ling_adjusted = ""
        gate_reason = ""

        if bulk_pass:
            report = score_linguistic_deterministic(name)
            ling_pass, ling_adjusted_val, gate_reason = evaluate_linguistic_gate(report)
            ling_score = report.overall_linguistic_score
            ling_adjusted = ling_adjusted_val

        rows.append({
            "domain_name": key,
            "tld": meta.get("tld") or (key.rsplit(".", 1)[-1] if "." in key else "com"),
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
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def run_funnel(
    limit: int | None = None,
    *,
    process_date: date | None = None,
    csv_path: Path | None = None,
) -> None:
    domains, process_date_label = _load_domains(process_date)
    if limit:
        domains = domains[:limit]
    names = [d["domain_name"] for d in domains]
    total = len(names)
    print(f"Input domains: {total} (DATA_SOURCE={settings.data_source}, process_date={process_date_label})")

    if total == 0:
        if settings.data_source == "file":
            print("No domains found. Add rows to data/seed_domains.csv")
        else:
            print(
                f"No domains found for process_date={process_date_label} in shortlisted_master_data_acqes_new. "
                "Confirm that batch exists in prod MySQL, or use DATA_SOURCE=file with seed_domains.csv."
            )
        return

    rows = build_report_rows(domains, process_date_label)
    bulk_pass_count = sum(1 for r in rows if r["bulk_pass"])
    ling_pass_count = sum(1 for r in rows if r["ling_pass"])

    print(f"Bulk pass:       {bulk_pass_count:5}  ({100 * bulk_pass_count / total:.1f}%)")
    print(f"Linguistic pass: {ling_pass_count:5}  ({100 * ling_pass_count / total:.1f}%)")

    tld_counts: dict[str, int] = {}
    for r in rows:
        tld_counts[r["tld"]] = tld_counts.get(r["tld"], 0) + 1
    print("\nTLD breakdown (input):")
    for tld, count in sorted(tld_counts.items(), key=lambda x: (-x[1], x[0])):
        print(f"  .{tld:8} {count:5}")

    print("\nTop linguistic pass candidates:")
    top = sorted(
        [r for r in rows if r["ling_pass"]],
        key=lambda r: float(r["ling_adjusted"] or 0),
        reverse=True,
    )
    for r in top[:25]:
        print(f"  {r['domain_name']:35} {float(r['ling_adjusted']):.1f}")

    if csv_path:
        write_csv(rows, csv_path)
        print(f"\nWrote {len(rows)} rows to {csv_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test bulk + linguistic filters")
    parser.add_argument("--sample", action="store_true", help="Run fixed sample domain list")
    parser.add_argument(
        "--funnel",
        action="store_true",
        help="Run funnel on configured input (seed_domains.csv or prod DB batch)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit domains (funnel mode)")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Override process_date for prod/temp (YYYY-MM-DD). Default: PIPELINE_PROCESS_DATE or yesterday.",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help=f"Write full per-domain report CSV (default with --funnel: {DEFAULT_CSV.name})",
    )
    args = parser.parse_args()

    process_date = date.fromisoformat(args.date) if args.date else None
    csv_path: Path | None = None
    if args.csv:
        csv_path = Path(args.csv)
    elif args.funnel:
        csv_path = DEFAULT_CSV

    if args.sample:
        run_sample()
    elif args.funnel:
        run_funnel(limit=args.limit, process_date=process_date, csv_path=csv_path)
    else:
        run_sample()
        print()
        run_funnel(limit=args.limit, process_date=process_date, csv_path=csv_path)


if __name__ == "__main__":
    main()
