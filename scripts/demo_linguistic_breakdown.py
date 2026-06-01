#!/usr/bin/env python3
"""Demo script: show per-dimension linguistic scores for 5 domains."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "schemas"))

from agents.linguistic_agent import evaluate_linguistic_gate, score_linguistic_deterministic

DEFAULT_DOMAINS = [
    "leadteam.ai",
    "neuralbank.ai",
    "payflow.io",
    "therapist.com",
    "growhub.net",
]

OUTPUT_FILE = ROOT / "data" / "demo_linguistic_breakdown.csv"

FIELDS = [
    "domain_name",
    "pronounceability",
    "memorability",
    "spelling_ease",
    "cross_language_safety",
    "word_segmentation",
    "brand_personality",
    "industry_fit",
    "novelty_score",
    "overall_linguistic_score",
    "adjusted_linguistic_score",
    "gate_passed",
    "gate_reason",
]


def build_rows(domains: list[str]) -> list[dict]:
    rows: list[dict] = []
    for domain in domains:
        report = score_linguistic_deterministic(domain.strip().lower())
        gate_passed, adjusted, gate_reason = evaluate_linguistic_gate(report)
        rows.append(
            {
                "domain_name": report.domain_name,
                "pronounceability": report.pronounceability,
                "memorability": report.memorability,
                "spelling_ease": report.spelling_ease,
                "cross_language_safety": report.cross_language_safety,
                "word_segmentation": report.word_segmentation,
                "brand_personality": report.brand_personality,
                "industry_fit": report.industry_fit,
                "novelty_score": report.novelty_score,
                "overall_linguistic_score": report.overall_linguistic_score,
                "adjusted_linguistic_score": adjusted,
                "gate_passed": gate_passed,
                "gate_reason": gate_reason,
            }
        )
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def print_table(rows: list[dict]) -> None:
    cols = [
        ("domain_name", 26),
        ("pronounceability", 5),
        ("memorability", 5),
        ("spelling_ease", 5),
        ("cross_language_safety", 5),
        ("word_segmentation", 5),
        ("brand_personality", 5),
        ("industry_fit", 5),
        ("novelty_score", 5),
        ("overall_linguistic_score", 7),
        ("adjusted_linguistic_score", 7),
        ("gate_passed", 5),
    ]
    header = " ".join(name[:width].ljust(width) for name, width in cols)
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            " ".join(
                str(row[name])[:width].ljust(width)
                for name, width in cols
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show detailed linguistic parameter scores for 5 domains."
    )
    parser.add_argument(
        "domains",
        nargs="*",
        help="Optional domain list. If omitted, uses 5 demo domains.",
    )
    parser.add_argument(
        "--csv",
        default=str(OUTPUT_FILE),
        help=f"Output CSV path (default: {OUTPUT_FILE})",
    )
    args = parser.parse_args()

    domains = args.domains if args.domains else DEFAULT_DOMAINS
    rows = build_rows(domains)
    print_table(rows)
    out_path = Path(args.csv)
    write_csv(rows, out_path)
    print(f"\nWrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    main()

