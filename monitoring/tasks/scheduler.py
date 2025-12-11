from apscheduler.schedulers.background import BackgroundScheduler


def build_scheduler(interval_seconds: int = 300):
    """Create a background scheduler with the run_all_checks job."""

    from monitoring.tasks.check_runner import run_all_checks

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_all_checks,
        "interval",
        seconds=interval_seconds,
        id="run_all_checks",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler
