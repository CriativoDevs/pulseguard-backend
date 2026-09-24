import os
import sys

from django.apps import AppConfig
from django.conf import settings


class MonitoringConfig(AppConfig):
    name = "monitoring"

    def ready(self):
        """Start the scheduler when Django is ready (skip in tests/migrations)."""
        auto_start = getattr(settings, "MONITORING_SCHEDULER_AUTO_START", True)
        if not auto_start:
            return

        skip_reasons = {"test", "makemigrations", "migrate", "collectstatic"}
        if any(arg in skip_reasons for arg in sys.argv):
            return
        if os.environ.get("MONITORING_SKIP_SCHEDULER_START"):
            return

        from monitoring.scheduler import start_scheduler

        start_scheduler()
