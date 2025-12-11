from django.db.models import Avg, Count, Max, Min, Q
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from monitoring.models import PingResult, Server, ServerStatus


def _org_ids(user):
    return list(user.memberships.values_list("organization_id", flat=True))


class MetricsViewSet(viewsets.ViewSet):
    """ViewSet for monitoring system metrics and statistics."""

    @action(detail=False, methods=["get"])
    def overview(self, request):
        """Get overall system metrics overview."""
        org_ids = _org_ids(request.user)

        total_servers = Server.objects.filter(organization_id__in=org_ids).count()
        active_servers = Server.objects.filter(
            organization_id__in=org_ids, status="active"
        ).count()

        # Server status breakdown
        status_counts = (
            ServerStatus.objects.filter(server__organization_id__in=org_ids)
            .values("status")
            .annotate(count=Count("id"))
        )
        status_breakdown = {item["status"]: item["count"] for item in status_counts}

        # Recent checks (last 24 hours)
        last_24h = timezone.now() - timezone.timedelta(hours=24)
        recent_checks = PingResult.objects.filter(
            check_timestamp__gte=last_24h, server__organization_id__in=org_ids
        )

        total_checks_24h = recent_checks.count()
        successful_checks = recent_checks.filter(status="success").count()
        failed_checks = recent_checks.filter(status__in=["timeout", "error"]).count()

        success_rate = (
            (successful_checks / total_checks_24h * 100) if total_checks_24h > 0 else 0
        )

        # Average response times
        avg_response_time = recent_checks.filter(
            status="success", response_time__isnull=False
        ).aggregate(avg=Avg("response_time"))["avg"]

        return Response(
            {
                "servers": {
                    "total": total_servers,
                    "active": active_servers,
                    "inactive": total_servers - active_servers,
                    "status_breakdown": {
                        "up": status_breakdown.get("up", 0),
                        "down": status_breakdown.get("down", 0),
                        "degraded": status_breakdown.get("degraded", 0),
                        "unknown": status_breakdown.get("unknown", 0),
                    },
                },
                "checks_last_24h": {
                    "total": total_checks_24h,
                    "successful": successful_checks,
                    "failed": failed_checks,
                    "success_rate": round(success_rate, 2),
                },
                "performance": {
                    "avg_response_time_ms": (
                        round(avg_response_time, 2) if avg_response_time else None
                    ),
                },
            }
        )

    @action(detail=False, methods=["get"])
    def uptime(self, request):
        """Get uptime statistics for all servers."""
        org_ids = _org_ids(request.user)
        servers = Server.objects.filter(status="active", organization_id__in=org_ids)
        uptime_data = []

        for server in servers:
            # Get checks from last 30 days
            last_30d = timezone.now() - timezone.timedelta(days=30)
            checks = PingResult.objects.filter(
                server=server, check_timestamp__gte=last_30d
            )

            total_checks = checks.count()
            successful_checks = checks.filter(status="success").count()

            uptime_percentage = (
                (successful_checks / total_checks * 100) if total_checks > 0 else 0
            )

            try:
                status = ServerStatus.objects.get(server=server)
                last_check = status.last_check
                current_status = status.status
            except ServerStatus.DoesNotExist:
                last_check = None
                current_status = "unknown"

            uptime_data.append(
                {
                    "server_id": server.id,  # type: ignore[attr-defined]
                    "server_name": server.name,
                    "url": server.full_url,
                    "uptime_percentage": round(uptime_percentage, 2),
                    "total_checks": total_checks,
                    "successful_checks": successful_checks,
                    "current_status": current_status,
                    "last_check": last_check,
                }
            )

        return Response({"servers": uptime_data})

    @action(detail=False, methods=["get"])
    def response_times(self, request):
        """Get response time statistics."""
        # Get time range from query params (default: last 24 hours)
        hours = int(request.query_params.get("hours", 24))
        since = timezone.now() - timezone.timedelta(hours=hours)

        org_ids = _org_ids(request.user)
        checks = PingResult.objects.filter(
            check_timestamp__gte=since,
            status="success",
            response_time__isnull=False,
            server__organization_id__in=org_ids,
        )

        stats = checks.aggregate(
            avg=Avg("response_time"),
            min=Min("response_time"),
            max=Max("response_time"),
            count=Count("id"),
        )

        # Get per-server breakdown
        server_stats = (
            checks.values("server__name", "server__host")
            .annotate(
                avg_response_time=Avg("response_time"),
                min_response_time=Min("response_time"),
                max_response_time=Max("response_time"),
                check_count=Count("id"),
            )
            .order_by("-avg_response_time")
        )

        return Response(
            {
                "period_hours": hours,
                "overall": {
                    "avg_ms": round(stats["avg"], 2) if stats["avg"] else None,
                    "min_ms": round(stats["min"], 2) if stats["min"] else None,
                    "max_ms": round(stats["max"], 2) if stats["max"] else None,
                    "total_checks": stats["count"],
                },
                "by_server": [
                    {
                        "server_name": item["server__name"],
                        "server_host": item["server__host"],
                        "avg_ms": round(item["avg_response_time"], 2),
                        "min_ms": round(item["min_response_time"], 2),
                        "max_ms": round(item["max_response_time"], 2),
                        "check_count": item["check_count"],
                    }
                    for item in server_stats
                ],
            }
        )

    @action(detail=False, methods=["get"])
    def failures(self, request):
        """Get failure statistics and recent failures."""
        # Get recent failures (last 7 days)
        last_7d = timezone.now() - timezone.timedelta(days=7)
        org_ids = _org_ids(request.user)
        failures = PingResult.objects.filter(
            check_timestamp__gte=last_7d,
            status__in=["timeout", "error"],
            server__organization_id__in=org_ids,
        )

        total_failures = failures.count()

        # Group by error type
        by_status = failures.values("status").annotate(count=Count("id"))
        status_breakdown = {item["status"]: item["count"] for item in by_status}

        # Recent failures with details
        recent_failures = (
            failures.select_related("server")
            .order_by("-check_timestamp")[:20]
            .values(
                "server__name",
                "server__host",
                "status",
                "error_message",
                "check_timestamp",
                "response_time",
            )
        )

        # Servers with most failures
        top_failing = (
            failures.values("server__name", "server__host")
            .annotate(failure_count=Count("id"))
            .order_by("-failure_count")[:10]
        )

        return Response(
            {
                "period_days": 7,
                "total_failures": total_failures,
                "by_type": {
                    "timeout": status_breakdown.get("timeout", 0),
                    "error": status_breakdown.get("error", 0),
                },
                "recent_failures": list(recent_failures),
                "top_failing_servers": list(top_failing),
            }
        )
