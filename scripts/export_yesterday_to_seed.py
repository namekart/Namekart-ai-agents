#!/usr/bin/env python3
"""Copy a prod shortlisted batch into data/seed_domains.csv for file-mode runs."""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from app.config import PROJECT_ROOT
from db.connection import SessionLocal
from db.queries import resolve_process_date

SEED_FILE = PROJECT_ROOT / "data" / "seed_domains.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export prod batch to seed_domains.csv")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="process_date YYYY-MM-DD (default: PIPELINE_PROCESS_DATE or yesterday)",
    )
    args = parser.parse_args()
    target_date = date.fromisoformat(args.date) if args.date else resolve_process_date()
    if not SessionLocal:
        print("DB not configured. Set DB_URL_PROD in .env")
        sys.exit(1)

    with SessionLocal() as session:
        rows = session.execute(
            text(
                """
                SELECT domain, tld, auction_price
                FROM shortlisted_master_data_acqes_new
                WHERE process_date = :d
                ORDER BY domain
                """
            ),
            {"d": target_date},
        ).fetchall()

    if not rows:
        print(f"No domains for process_date={target_date}")
        sys.exit(1)

    SEED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SEED_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["domain_name", "tld", "auction_price", "auction_bidders"],
        )
        writer.writeheader()
        for domain, tld, auction_price in rows:
            name = (domain or "").strip().lower()
            if not name:
                continue
            writer.writerow({
                "domain_name": name,
                "tld": tld or (name.rsplit(".", 1)[-1] if "." in name else "com"),
                "auction_price": auction_price or 0,
                "auction_bidders": 0,
            })

    print(f"Wrote {len(rows)} domains to {SEED_FILE}")
    print("Set DATA_SOURCE=file in .env, then POST /trigger to run fully offline.")


if __name__ == "__main__":
    main()
