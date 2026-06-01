import csv
from fastapi import APIRouter, BackgroundTasks, HTTPException
from datetime import date

from app.scheduler import scheduled_job
from app.config import settings, PROJECT_ROOT
from db.queries import (
    RESULTS_OUTPUT_FILE,
    RESULTS_PREVIOUS_FILE,
    get_results_status,
    load_latest_results_from_csv,
    mark_pipeline_results_started,
)

router = APIRouter()

DATA_DIR = PROJECT_ROOT / "data"
SEED_FILE = DATA_DIR / "seed_domains.csv"
RESULTS_FILE = RESULTS_OUTPUT_FILE

# Simple global state for status tracking in memory
pipeline_status = {
    "status": "idle",
    "counts": {
        "total": 0,
        "filtered": 0,
        "evaluated": 0,
        "strong_buy": 0,
    },
}


def _count_seed_domains() -> int:
    if not SEED_FILE.exists():
        return 0
    with open(SEED_FILE, "r", encoding="utf-8") as f:
        return max(0, sum(1 for _ in f) - 1)


def _count_results() -> tuple[int, int]:
    """Returns (total_results, strong_buy_count)."""
    if not RESULTS_FILE.exists():
        return 0, 0
    total = 0
    strong_buys = 0
    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            if row.get("decision") == "STRONG_BUY":
                strong_buys += 1
    return total, strong_buys


def _count_db_results() -> tuple[int, int]:
    """Returns (total_results, strong_buy_count) from MySQL when in prod/temp mode."""
    from db.connection import SessionLocal
    from db.models import AgentEvaluationResult

    if not SessionLocal:
        return 0, 0
    try:
        with SessionLocal() as db:
            records = db.query(AgentEvaluationResult).all()
            strong = sum(1 for r in records if r.decision == "STRONG_BUY")
            return len(records), strong
    except Exception:
        return 0, 0


def _refresh_counts() -> None:
    total_results, strong_buys = _count_results()
    pipeline_status["counts"]["evaluated"] = total_results
    pipeline_status["counts"]["filtered"] = total_results
    pipeline_status["counts"]["strong_buy"] = strong_buys
    if settings.data_source == "file":
        pipeline_status["counts"]["total"] = _count_seed_domains()
    elif pipeline_status["counts"]["total"] == 0:
        pipeline_status["counts"]["total"] = total_results


@router.post("/trigger")
def trigger_pipeline(background_tasks: BackgroundTasks):
    """Manually trigger full pipeline run."""
    if pipeline_status["status"] == "running":
        raise HTTPException(
            status_code=409,
            detail="Pipeline already running. Wait for it to finish or check server logs.",
        )

    pipeline_status["status"] = "running"
    job_id = f"trigger-{date.today()}"

    # Delete current CSV immediately; archive previous run for diffing
    mark_pipeline_results_started(job_id)

    def run_and_update():
        try:
            scheduled_job(job_id=job_id)
        finally:
            pipeline_status["status"] = "idle"
            _refresh_counts()

    background_tasks.add_task(run_and_update)
    results_status = get_results_status()
    return {
        "status": "accepted",
        "message": "Pipeline run triggered in background",
        "job_id": job_id,
        "data_source": settings.data_source,
        "seed_domains": _count_seed_domains() if settings.data_source == "file" else None,
        "results_cleared": True,
        "previous_results_file": results_status.get("previous_results_file"),
        "results_status": results_status,
    }


@router.post("/run-pipeline")
def run_pipeline(background_tasks: BackgroundTasks):
    """Alias for /trigger — matches walkthrough docs and curl commands."""
    return trigger_pipeline(background_tasks)


@router.get("/status")
def get_status():
    """Returns current run status + counts."""
    _refresh_counts()
    results_status = get_results_status()
    return {
        **pipeline_status,
        "data_source": settings.data_source,
        "seed_file": str(SEED_FILE),
        "results_file": str(RESULTS_FILE) if RESULTS_FILE.exists() else None,
        "previous_results_file": str(RESULTS_PREVIOUS_FILE) if RESULTS_PREVIOUS_FILE.exists() else None,
        "results_status": results_status,
    }


@router.get("/results")
def get_results(target_date: date = None):
    """Returns ranked pipeline results from data/results_output.csv."""
    if target_date is None:
        target_date = date.today()

    results_status = get_results_status()
    state = results_status.get("state", "idle")

    if state == "running":
        return {
            "date": target_date,
            "results": [],
            "count": 0,
            "results_status": results_status,
            "message": results_status.get("message"),
        }

    results = load_latest_results_from_csv()
    return {
        "date": target_date,
        "results": results,
        "source": "results_output.csv",
        "results_file": str(RESULTS_FILE) if RESULTS_FILE.exists() else None,
        "previous_results_file": str(RESULTS_PREVIOUS_FILE) if RESULTS_PREVIOUS_FILE.exists() else None,
        "count": len(results),
        "results_status": results_status,
    }
