from django.core.management.base import BaseCommand, CommandError

from monitoring.models import Server
from monitoring.tasks.check_runner import run_all_checks


class Command(BaseCommand):
    help = "Run health checks on all active servers"

    def add_arguments(self, parser):
        parser.add_argument(
            "--org-id",
            type=int,
            help="Limit checks to servers in a specific organization",
        )
        parser.add_argument(
            "--server-id",
            type=int,
            help="Run check on a specific server",
        )

    def handle(self, *args, **options):
        queryset = Server.objects.filter(status="active")

        if options["org_id"]:
            queryset = queryset.filter(organization_id=options["org_id"])

        if options["server_id"]:
            queryset = queryset.filter(id=options["server_id"])

        if not queryset.exists():
            self.stdout.write(self.style.WARNING("No active servers found for checks."))
            return

        self.stdout.write(
            self.style.SUCCESS(f"Running checks for {queryset.count()} server(s)...")
        )

        results = run_all_checks(queryset=queryset)

        for server_id, status_val in results:
            self.stdout.write(self.style.SUCCESS(f"  Server {server_id}: {status_val}"))

        self.stdout.write(
            self.style.SUCCESS(f"\nCompleted {len(results)} check(s) successfully.")
        )
