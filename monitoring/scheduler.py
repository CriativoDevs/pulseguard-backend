"""
Scheduler management for background health checks.
Integrates APScheduler with Django lifecycle (apps.ready, server shutdown).
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler_instance = None


def get_scheduler():
    """Get or create the global scheduler instance."""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = BackgroundScheduler(daemon=True)
    return _scheduler_instance


def start_scheduler():
    """Start the scheduler and add jobs based on active servers."""
    global _scheduler_instance
    scheduler = get_scheduler()

    if scheduler.running:
        logger.info("Scheduler already running.")
        return

    # Remove existing jobs
    scheduler.remove_all_jobs()

    # Add jobs for each active server
    from monitoring.models import Server
    from monitoring.tasks.check_runner import run_all_checks

    active_servers = Server.objects.filter(status="active")
    if not active_servers.exists():
        logger.warning("No active servers to schedule checks for.")
    else:
        # For now, schedule a global check every 5 minutes (300s) by default
        # Future: per-server scheduling based on check_interval
        scheduler.add_job(
            run_all_checks,
            "interval",
            seconds=300,  # Default interval
            id="run_all_checks_global",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info(
            f"Scheduler: added global check job for {active_servers.count()} server(s)"
        )

    try:
        scheduler.start()
        logger.info("Health check scheduler started.")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    global _scheduler_instance
    if _scheduler_instance and _scheduler_instance.running:
        try:
            _scheduler_instance.shutdown(wait=True)
            logger.info("Health check scheduler stopped.")
        except Exception as e:
            logger.error(f"Error stopping scheduler: {e}")


def is_scheduler_running():
    """Check if scheduler is running."""
    scheduler = get_scheduler()
    return scheduler.running


def get_scheduler_jobs():
    """Get list of scheduled jobs."""
    scheduler = get_scheduler()
    return [
        {
            "id": job.id,
            "name": job.name,
            "next_run_time": job.next_run_time,
            "trigger": str(job.trigger),
        }
        for job in scheduler.get_jobs()
    ]
