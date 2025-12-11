from django.core.management.base import BaseCommand

from monitoring.tasks.check_runner import run_all_checks


class Command(BaseCommand):
    help = "Run health checks for all active servers"

    def handle(self, *args, **options):
        results = run_all_checks()
        self.stdout.write(self.style.SUCCESS(f"Ran {len(results)} checks"))
        for server_id, status in results:
            self.stdout.write(f"Server {server_id}: {status}")
