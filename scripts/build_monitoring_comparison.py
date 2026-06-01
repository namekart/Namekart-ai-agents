#!/usr/bin/env python3
"""Build a side-by-side run comparison table for linguistic demo monitoring."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MONITOR_DIR = ROOT / "data" / "monitoring"
RUN_FILES = [
    MONITOR_DIR / "demo_linguistic_breakdown_run1.csv",
    MONITOR_DIR / "demo_linguistic_breakdown_run2.csv",
    MONITOR_DIR / "demo_linguistic_breakdown_run3.csv",
]

OUT_CSV = MONITOR_DIR / "demo_linguistic_comparison_table.csv"
OUT_MD = MONITOR_DIR / "demo_linguistic_comparison_table.md"

METRICS = [
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
]


def load_run(path: Path) -> dict[str, dict]:
    with open(path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {row["domain_name"]: row for row in rows}


def build_comparison_rows(run_maps: list[dict[str, dict]]) -> list[dict]:
    domains = sorted(set().union(*[set(m.keys()) for m in run_maps]))
    out_rows: list[dict] = []
    for domain in domains:
        row = {"domain_name": domain}
        for idx, run in enumerate(run_maps, start=1):
            data = run.get(domain, {})
            for metric in METRICS:
                row[f"run{idx}_{metric}"] = data.get(metric, "")
        out_rows.append(row)
    return out_rows


def write_csv(rows: list[dict]) -> None:
    fields = ["domain_name"]
    for run_idx in (1, 2, 3):
        fields.extend([f"run{run_idx}_{m}" for m in METRICS])

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict]) -> None:
    # Compact markdown view focused on overall and gate across runs.
    lines = []
    lines.append("# Linguistic Demo Run Comparison")
    lines.append("")
    lines.append("| Domain | Run1 Overall | Run1 Adjusted | Run1 Gate | Run2 Overall | Run2 Adjusted | Run2 Gate | Run3 Overall | Run3 Adjusted | Run3 Gate |")
    lines.append("|---|---:|---:|:---:|---:|---:|:---:|---:|---:|:---:|")
    for row in rows:
        lines.append(
            f"| {row['domain_name']} "
            f"| {row['run1_overall_linguistic_score']} | {row['run1_adjusted_linguistic_score']} | {row['run1_gate_passed']} "
            f"| {row['run2_overall_linguistic_score']} | {row['run2_adjusted_linguistic_score']} | {row['run2_gate_passed']} "
            f"| {row['run3_overall_linguistic_score']} | {row['run3_adjusted_linguistic_score']} | {row['run3_gate_passed']} |"
        )

    lines.append("")
    lines.append("Full side-by-side metric table is available in `demo_linguistic_comparison_table.csv`.")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    run_maps = [load_run(path) for path in RUN_FILES]
    rows = build_comparison_rows(run_maps)
    write_csv(rows)
    write_markdown(rows)
    print(f"Wrote {len(rows)} domains to {OUT_CSV}")
    print(f"Wrote visual markdown table to {OUT_MD}")


if __name__ == "__main__":
    main()

