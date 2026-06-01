import csv
import json
import logging
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session

from app.config import settings, PROJECT_ROOT
from db.models import ShortlistedMasterDataAcqes, AgentEvaluationResult

logger = logging.getLogger(__name__)

RESULT_CSV_FIELDS = [
    "domain_name",
    "decision",
    "final_score",
    "linguistic_score",
    "bulk_score",
    "valuation_score",
    "gate_passed",
]
RESULTS_OUTPUT_FILE = PROJECT_ROOT / "data" / "results_output.csv"
RESULTS_PREVIOUS_FILE = PROJECT_ROOT / "data" / "results_output.previous.csv"
RESULTS_STATUS_FILE = PROJECT_ROOT / "data" / "results_output.status.json"


def _write_results_status(payload: Dict[str, Any]) -> None:
    RESULTS_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_STATUS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_results_status() -> Dict[str, Any]:
    """Read pipeline results file state (for /status and /results)."""
    if RESULTS_STATUS_FILE.exists():
        try:
            return json.loads(RESULTS_STATUS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    ready = RESULTS_OUTPUT_FILE.exists()
    return {
        "state": "ready" if ready else "idle",
        "results_file": str(RESULTS_OUTPUT_FILE) if ready else None,
        "previous_results_file": str(RESULTS_PREVIOUS_FILE) if RESULTS_PREVIOUS_FILE.exists() else None,
        "row_count": _count_csv_rows(RESULTS_OUTPUT_FILE) if ready else 0,
    }


def _count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


def mark_pipeline_results_started(job_id: Optional[str] = None) -> None:
    """
    Called when POST /trigger is accepted (and at cron job start).
    Archives the last CSV for diffing, deletes the current CSV, marks status=running.
    """
    RESULTS_OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    if RESULTS_OUTPUT_FILE.exists():
        shutil.copy2(RESULTS_OUTPUT_FILE, RESULTS_PREVIOUS_FILE)
        RESULTS_OUTPUT_FILE.unlink()

    for stale in (RESULTS_OUTPUT_FILE.with_suffix(".meta.txt"),):
        try:
            stale.unlink()
        except FileNotFoundError:
            pass

    _write_results_status({
        "state": "running",
        "job_id": job_id or f"run-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
        "started_at": datetime.utcnow().isoformat() + "Z",
        "results_file": None,
        "previous_results_file": str(RESULTS_PREVIOUS_FILE) if RESULTS_PREVIOUS_FILE.exists() else None,
        "message": "Pipeline running — results_output.csv will be recreated when finished.",
    })
    logger.info(
        "Results cleared for new run; previous run archived at %s",
        RESULTS_PREVIOUS_FILE if RESULTS_PREVIOUS_FILE.exists() else "(none)",
    )


def mark_pipeline_results_ready(row_count: int, csv_path: str) -> None:
    _write_results_status({
        "state": "ready",
        "finished_at": datetime.utcnow().isoformat() + "Z",
        "results_file": csv_path,
        "previous_results_file": str(RESULTS_PREVIOUS_FILE) if RESULTS_PREVIOUS_FILE.exists() else None,
        "row_count": row_count,
        "message": f"Results ready — {row_count} domains in results_output.csv",
    })


def mark_pipeline_results_finished(state: str, message: str) -> None:
    """state: skipped | failed"""
    _write_results_status({
        "state": state,
        "finished_at": datetime.utcnow().isoformat() + "Z",
        "results_file": str(RESULTS_OUTPUT_FILE) if RESULTS_OUTPUT_FILE.exists() else None,
        "previous_results_file": str(RESULTS_PREVIOUS_FILE) if RESULTS_PREVIOUS_FILE.exists() else None,
        "row_count": _count_csv_rows(RESULTS_OUTPUT_FILE),
        "message": message,
    })

def resolve_process_date(override: Optional[date] = None) -> date:
    """DB batch date: explicit override, then PIPELINE_PROCESS_DATE, else yesterday."""
    if override is not None:
        return override
    raw = (settings.pipeline_process_date or "").strip()
    if raw:
        return date.fromisoformat(raw)
    return date.today() - timedelta(days=1)


def get_todays_domains(
    session: Session = None,
    *,
    process_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    if settings.data_source == "file":
        domains = []
        seed_file = PROJECT_ROOT / "data" / "seed_domains.csv"
        try:
            with open(seed_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = (row.get("domain_name") or row.get("domain") or "").strip().lower()
                    if not name:
                        continue
                    tld = name.rsplit(".", 1)[-1] if "." in name else "com"
                    domains.append({
                        "domain_name": name,
                        "tld": row.get("tld") or tld,
                        "auction_price": float(row.get("auction_price", 0) or 0),
                        "auction_bidders": int(float(row.get("auction_bidders", 0) or 0)),
                    })
        except FileNotFoundError:
            pass
        return domains
    else:
        if not session:
            return []
        target_date = resolve_process_date(process_date)
        records = session.query(ShortlistedMasterDataAcqes).filter(
            ShortlistedMasterDataAcqes.process_date == target_date
        ).all()
        logger.info(
            "Loaded domains from shortlisted_master_data_acqes_new",
            process_date=str(target_date),
            count=len(records),
        )
        out = []
        for r in records:
            name = (r.domain or "").strip().lower()
            tld = name.rsplit(".", 1)[-1] if "." in name else "com"
            out.append({
                "domain_name": name,
                "tld": tld,
                "auction_price": float(r.auction_price or 0),
                "auction_bidders": 0,
            })
        return out

def _write_to_csv(result: Dict[str, Any]):
    """Append one row — prefer write_evaluation_results_batch for full runs."""
    write_evaluation_results_batch([result])


def _export_results_csv(sorted_results: List[Dict[str, Any]], output_file: Path) -> Path:
    """Write ranked results to a local CSV (always available regardless of DB grants)."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_CSV_FIELDS)
        writer.writeheader()
        for row in sorted_results:
            writer.writerow({k: row.get(k, "") for k in RESULT_CSV_FIELDS})
    return output_file


def write_evaluation_results_batch(
    results: List[Dict[str, Any]], session: Session = None
) -> Dict[str, Any]:
    """
    Persist pipeline results. Returns summary dict with db_saved, csv_path, row_count.

    - file mode: results_output.csv only
    - prod/temp: tries agent_evaluation_results (needs INSERT/DELETE/SELECT grants);
      always also writes data/last_pipeline_results.csv so results are not lost
    """
    if not results:
        mark_pipeline_results_finished("failed", "No ranked results to write.")
        return {"db_saved": False, "csv_path": None, "row_count": 0}

    sorted_results = sorted(
        results,
        key=lambda r: float(r.get("final_score") or 0),
        reverse=True,
    )
    row_count = len(sorted_results)

    csv_path = _export_results_csv(sorted_results, RESULTS_OUTPUT_FILE)
    mark_pipeline_results_ready(row_count, str(csv_path))

    db_saved = False
    if not getattr(settings, "save_results_to_db", False):
        return {"db_saved": False, "csv_path": str(csv_path), "row_count": row_count}

    if not session:
        logger.warning(
            "save_results_to_db is enabled but no DB session — results at %s only",
            csv_path,
        )
        return {"db_saved": False, "csv_path": str(csv_path), "row_count": row_count}

    try:
        session.query(AgentEvaluationResult).delete()
        for row in sorted_results:
            session.add(AgentEvaluationResult(
                domain_name=row.get("domain_name"),
                decision=row.get("decision"),
                thesis=row.get("thesis"),
                linguistic_score=row.get("linguistic_score"),
                market_score=row.get("market_score"),
                valuation_score=row.get("valuation_score"),
            ))
        session.commit()
        db_saved = True
    except Exception as exc:
        session.rollback()
        logger.error(
            "Could not write agent_evaluation_results: %s — see %s",
            exc,
            csv_path,
        )

    return {"db_saved": db_saved, "csv_path": str(csv_path), "row_count": row_count}


def write_evaluation_result(result: Dict[str, Any], session: Session = None) -> None:
    write_evaluation_results_batch([result], session)


def load_latest_results_from_csv() -> List[Dict[str, Any]]:
    """Read last pipeline export from data/results_output.csv."""
    if not RESULTS_OUTPUT_FILE.exists():
        return []
    with open(RESULTS_OUTPUT_FILE, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def clear_evaluation_results(session: Session = None) -> None:
    """Legacy alias — prefer mark_pipeline_results_started() at run start."""
    mark_pipeline_results_started()

    if getattr(settings, "save_results_to_db", False) and session:
        try:
            session.query(AgentEvaluationResult).delete()
            session.commit()
        except Exception:
            session.rollback()
