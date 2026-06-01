import time
import pytz
import structlog
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from agents.pipeline import graph
from agents.scoring import build_linguistic_only_candidates, rank_domains_linguistic_only
from db.queries import (
    get_todays_domains,
    mark_pipeline_results_finished,
    mark_pipeline_results_started,
    write_evaluation_results_batch,
)
from db.connection import SessionLocal

logger = structlog.get_logger()
scheduler = BackgroundScheduler()


def scheduled_job(job_id: str | None = None):
    logger.info(
        "Scheduler triggered pipeline run",
        data_source=settings.data_source,
        mode="bulk_classifier + linguistic_agent only",
    )
    from tools.java_api_client import push_winners

    if job_id is None:
        mark_pipeline_results_started()

    session = None
    if settings.data_source in ("temp", "prod") and SessionLocal:
        session = SessionLocal()

    try:
        domains = get_todays_domains(session)
        if not domains:
            logger.info("No domains found. Skipping pipeline.")
            mark_pipeline_results_finished("skipped", "No input domains for configured process_date.")
            return

        start_time = time.time()
        logger.info("Starting pipeline execution", domain_count=len(domains))

        state = graph.invoke({
            "raw_domains": domains,
            "errors": [],
            "bulk_reports": {},
            "linguistic_reports": {},
            "skipped_domains": [],
        })

        linguistic_reports = {
            k.strip().lower(): v for k, v in state.get("linguistic_reports", {}).items()
        }
        bulk_reports = state.get("bulk_reports", {})

        filtered_rows = state.get("filtered_domains", [])
        candidates = build_linguistic_only_candidates(
            filtered_rows, linguistic_reports, bulk_reports
        )
        ranked = rank_domains_linguistic_only(candidates)

        logger.info(
            "Ranking complete",
            bulk_passed=len(filtered_rows),
            linguistic_scored=len(candidates),
            strong_buy=sum(1 for r in ranked if r["decision"] == "STRONG_BUY"),
            buy=sum(1 for r in ranked if r["decision"] == "BUY"),
            maybe=sum(1 for r in ranked if r["decision"] == "MAYBE"),
            skip=sum(1 for r in ranked if r["decision"] == "SKIP"),
        )

        results = [
            {
                "domain_name": r["domain_name"],
                "decision": r["decision"],
                "final_score": r["final_score"],
                "linguistic_score": r["linguistic_score"],
                "bulk_score": r.get("bulk_score", ""),
                "valuation_score": r.get("valuation_score", ""),
                "gate_passed": r.get("gate_passed", False),
            }
            for r in ranked
        ]

        persist = write_evaluation_results_batch(results, session)

        strong_buy_domains = [r["domain_name"] for r in ranked if r["decision"] == "STRONG_BUY"]

        elapsed = time.time() - start_time
        logger.info(
            "Pipeline completed",
            duration_seconds=round(elapsed, 2),
            errors=state.get("errors", []),
            ranked=len(results),
            db_saved=persist.get("db_saved"),
            results_csv=persist.get("csv_path"),
        )
        if persist.get("csv_path"):
            logger.info("Results CSV ready", path=persist.get("csv_path"))

        if settings.data_source == "prod":
            push_winners(strong_buy_domains)

    except Exception as exc:
        mark_pipeline_results_finished("failed", str(exc))
        logger.exception("Pipeline run encountered an error", exc_info=True)
    finally:
        if session:
            session.close()


def start_scheduler():
    logger.info("Starting APScheduler", hour=settings.cron_hour, minute=settings.cron_minute)
    scheduler.add_job(
        scheduled_job,
        "cron",
        hour=settings.cron_hour,
        minute=settings.cron_minute,
        timezone=pytz.utc,
        id="daily_pipeline",
        replace_existing=True,
    )
    scheduler.start()
