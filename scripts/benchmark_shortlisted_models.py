#!/usr/bin/env python3
"""Run shortlist pipeline across multiple MODEL_FAST values and save structured reports."""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RUNNER = ROOT / "scripts" / "export_reports_from_csv.py"

MODEL_LINES = [
    "minimax/minimax-m2.7",
    "tencent/hy3-preview",
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-pro",
    "anthropic/claude-sonnet-4.6",
    "google/gemini-3.5-flash",
    "google/gemini-3.1-flash-lite-preview",
    "moonshotai/kimi-k2.6",
    "meta-llama/llama-3.1-8b-instruct",
    "meta-llama/llama-4-maverick",
    "openai/gpt-4o-mini",
    "openai/gpt-oss-120b",
    "openai/gpt-5.4-nano",
]


def slugify(model: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", model).strip("_")


def read_counts(folder: Path) -> dict[str, int]:
    pipe = list(csv.DictReader((folder / "pipeline_results.csv").open(encoding="utf-8")))
    all_rows = list(csv.DictReader((folder / "all_domains_report.csv").open(encoding="utf-8")))
    bulk = list(csv.DictReader((folder / "bulk_shortlisted.csv").open(encoding="utf-8")))
    ling = list(csv.DictReader((folder / "linguistic_shortlisted.csv").open(encoding="utf-8")))
    dec = Counter(r.get("decision", "") for r in pipe)
    return {
        "input_domains": len(all_rows),
        "bulk_shortlisted": len(bulk),
        "linguistic_shortlisted": len(ling),
        "pipeline_results": len(pipe),
        "strong_buy": dec.get("STRONG_BUY", 0),
        "buy": dec.get("BUY", 0),
        "maybe": dec.get("MAYBE", 0),
        "skip": dec.get("SKIP", 0),
    }


def run_one(model: str, input_csv: Path, out_root: Path, limit: int | None) -> dict[str, str | int]:
    model_slug = slugify(model)
    outdir = out_root / model_slug
    outdir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["MODEL_FAST"] = model
    env["ENFORCE_DETERMINISTIC_PIPELINE"] = "false"
    env["USE_LLM_BULK_CLASSIFIER"] = "true"
    env["USE_LLM_LINGUISTIC"] = "true"
    env["BULK_LLM_BATCH_SIZE"] = "100"
    env["REQUEST_DELAY_SECONDS"] = "0.6"

    cmd = [
        "uv",
        "run",
        "python",
        str(RUNNER),
        str(input_csv),
        "--outdir",
        str(outdir),
    ]
    cmd.extend(["--ling-batch-size", "50"])
    if limit:
        cmd.extend(["--limit", str(limit)])

    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        (outdir / "run_error.log").write_text(proc.stderr + "\n" + proc.stdout, encoding="utf-8")
        return {
            "model": model,
            "status": "failed",
            "details": "see run_error.log",
            "folder": str(outdir),
        }

    counts = read_counts(outdir)
    return {
        "model": model,
        "status": "ok",
        "folder": str(outdir),
        **counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Shortlisted_Domains.csv across models.")
    parser.add_argument(
        "--input",
        default=str(DATA / "Shortlisted_Domains.csv"),
        help="Input CSV path",
    )
    parser.add_argument(
        "--out-root",
        default=str(DATA / "model_benchmark_shortlisted_domains"),
        help="Output root folder",
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional domain limit for faster run")
    parser.add_argument(
        "--models",
        nargs="*",
        default=MODEL_LINES,
        help="Model list; default uses predefined list from your .env note",
    )
    args = parser.parse_args()

    input_csv = Path(args.input)
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict[str, str | int]] = []
    for model in args.models:
        print(f"Running model: {model}")
        result = run_one(model, input_csv, out_root, args.limit)
        summary_rows.append(result)
        print(f"  -> {result.get('status')} ({result.get('folder')})")

    summary_path = out_root / "summary.csv"
    fields = [
        "model",
        "status",
        "input_domains",
        "bulk_shortlisted",
        "linguistic_shortlisted",
        "pipeline_results",
        "strong_buy",
        "buy",
        "maybe",
        "skip",
        "folder",
        "details",
    ]
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(summary_rows)

    print(f"\nWrote benchmark summary: {summary_path}")


if __name__ == "__main__":
    main()

