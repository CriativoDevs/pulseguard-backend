from typing import Iterable, List, Tuple

from django.utils import timezone

from monitoring.models import PingResult, Server, ServerStatus
from monitoring.services.check_service import HealthCheckService
from monitoring.services.notification_service import NotificationService
from monitoring.consumers import notify_subscribers


def run_all_checks(
    service: HealthCheckService | None = None,
    now=None,
    queryset: Iterable[Server] | None = None,
    send_notifications: bool = True,
) -> List[Tuple[int, str]]:
    """Run checks for all active servers and persist results.

    Returns list of tuples (server_id, status).
    """

    service = service or HealthCheckService()
    now = now or timezone.now()
    servers = (
        queryset if queryset is not None else Server.objects.filter(status="active")
    )
    notification_service = NotificationService() if send_notifications else None

    results: List[Tuple[int, str]] = []
    for server in servers:
        data = service.run_check(server)

        ping = PingResult.objects.create(
            server=server,
            status=data["status"],
            response_time=data.get("response_time"),
            status_code=data.get("status_code"),
            error_message=data.get("error_message"),
            check_timestamp=now,
        )

        status_obj, created = ServerStatus.objects.get_or_create(server=server)
        old_status = status_obj.status
        status_obj.last_check = now

        if data["status"] == "success":
            status_obj.consecutive_failures = 0
            status_obj.status = "up"
            status_obj.last_up = now
            status_obj.message = "OK"
        else:
            status_obj.consecutive_failures += 1
            status_obj.last_down = now
            status_obj.message = data.get("error_message") or data["status"]
            if status_obj.consecutive_failures >= status_obj.failure_threshold:
                status_obj.status = "down"
            else:
                status_obj.status = "degraded"

        status_obj.save()

        # Send WebSocket notifications
        notify_subscribers(ping, status_obj)

        # Send email/SMS notifications if status changed
        if notification_service and old_status != status_obj.status:
            notification_service.notify_status_change(server, status_obj, old_status)

        results.append((server.id, data["status"]))

    return results
