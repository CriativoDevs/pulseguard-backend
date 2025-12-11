import time

from django.core.management.base import BaseCommand

from monitoring.tasks.scheduler import build_scheduler


class Command(BaseCommand):
    help = "Start APScheduler to run periodic health checks"

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=int,
            default=300,
            help="Interval in seconds between check runs (default: 300)",
        )
        parser.add_argument(
            "--no-loop",
            action="store_true",
            help="Start and exit immediately (useful for tests)",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        no_loop = options["no_loop"]

        scheduler = build_scheduler(interval_seconds=interval)
        scheduler.start()

        self.stdout.write(
            self.style.SUCCESS(f"Scheduler started (interval={interval}s)")
        )

        if no_loop:
            scheduler.shutdown(wait=False)
            return

        self.stdout.write("Press Ctrl+C to stop scheduler")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write("Stopping scheduler...")
            scheduler.shutdown(wait=False)
            self.stdout.write(self.style.SUCCESS("Scheduler stopped"))
