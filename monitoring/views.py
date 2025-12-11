import json
from django.http import StreamingHttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import permissions, status as drf_status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Membership,
    NotificationConfig,
    Organization,
    PingResult,
    Plan,
    Server,
    ServerStatus,
    UserAccount,
)
from .serializers import (
    MembershipSerializer,
    OrganizationSerializer,
    NotificationConfigSerializer,
    PingResultSerializer,
    ServerSerializer,
    ServerStatusSerializer,
)


def _organization_ids(user):
    return list(user.memberships.values_list("organization_id", flat=True))


def _ensure_default_org(user):
    org = user.memberships.first().organization if user.memberships.exists() else None
    if org:
        return org
    org = Organization.objects.create(name=f"{user.username}-org", owner=user)
    Membership.objects.create(user=user, organization=org, role="owner")
    UserAccount.objects.create(organization=org, plan=None)
    return org


def _is_org_admin(user, organization: Organization) -> bool:
    return Membership.objects.filter(
        user=user, organization=organization, role__in=["owner", "admin"]
    ).exists()


class ServerViewSet(viewsets.ModelViewSet):
    serializer_class = ServerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org_ids = _organization_ids(self.request.user)
        return Server.objects.filter(organization_id__in=org_ids).order_by("name")

    def perform_create(self, serializer):
        org = _ensure_default_org(self.request.user)
        serializer.save(owner=self.request.user, organization=org)


class PingResultViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PingResultSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org_ids = _organization_ids(self.request.user)
        return PingResult.objects.select_related("server").filter(
            server__organization_id__in=org_ids
        )


class ServerStatusViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ServerStatusSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org_ids = _organization_ids(self.request.user)
        return ServerStatus.objects.select_related("server").filter(
            server__organization_id__in=org_ids
        )


class NotificationConfigViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationConfigSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org_ids = _organization_ids(self.request.user)
        return NotificationConfig.objects.select_related("server").filter(
            server__organization_id__in=org_ids
        )

    def perform_create(self, serializer):
        org = _ensure_default_org(self.request.user)
        server = serializer.validated_data.get("server")
        if server and server.organization_id not in _organization_ids(
            self.request.user
        ):
            raise PermissionDenied("Server not in your organization")
        serializer.save()


class RunChecksView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from .tasks.check_runner import run_all_checks

        if request.user.is_staff:
            org_ids = _organization_ids(request.user)
        else:
            admin_orgs = Membership.objects.filter(
                user=request.user, role__in=["owner", "admin"]
            )
            if not admin_orgs.exists():
                raise PermissionDenied("Only admins can run checks")
            org_ids = list(admin_orgs.values_list("organization_id", flat=True))
        queryset = Server.objects.filter(organization_id__in=org_ids)
        if not org_ids:
            return Response({"count": 0, "results": []})
        results = run_all_checks(queryset=queryset)
        return Response({"count": len(results), "results": results})


class ServerStatusStreamView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        status_filter = request.query_params.get("status")
        server_ids = request.query_params.get("server_id")
        since_param = request.query_params.get("since")
        ping_limit = int(request.query_params.get("limit", 50))

        if since_param and " " in since_param:
            # Handle unencoded plus signs turned into spaces
            since_param = since_param.replace(" ", "+")

        since_dt = parse_datetime(since_param) if since_param else None
        if since_dt and timezone.is_naive(since_dt):
            since_dt = timezone.make_aware(since_dt)

        def event_stream():
            # Inform client to retry after 5s if connection drops
            yield "retry: 5000\n\n"
            qs = ServerStatus.objects.select_related("server").filter(
                server__organization_id__in=_organization_ids(request.user)
            )
            if status_filter:
                qs = qs.filter(status=status_filter)
            if server_ids:
                ids = [sid for sid in server_ids.split(",") if sid]
                qs = qs.filter(server__id__in=ids)
            if since_dt:
                qs = qs.filter(updated_at__gt=since_dt)

            statuses = qs.order_by("server__name")
            for status in statuses:
                payload = {
                    "server": status.server.id,
                    "name": status.server.name,
                    "status": status.status,
                    "uptime_percentage": status.uptime_percentage,
                    "last_check": (
                        status.last_check.isoformat() if status.last_check else None
                    ),
                    "last_up": status.last_up.isoformat() if status.last_up else None,
                    "last_down": (
                        status.last_down.isoformat() if status.last_down else None
                    ),
                    "message": status.message,
                }
                yield f"event: status\ndata: {json.dumps(payload)}\n\n"

            pings = PingResult.objects.select_related("server").filter(
                server__organization_id__in=_organization_ids(request.user)
            )
            if server_ids:
                ids = [sid for sid in server_ids.split(",") if sid]
                pings = pings.filter(server__id__in=ids)
            if since_dt:
                pings = pings.filter(check_timestamp__gt=since_dt)
            pings = pings.order_by("-check_timestamp")[:ping_limit]

            for ping in pings:
                payload = {
                    "server": ping.server.id,
                    "name": ping.server.name,
                    "status": ping.status,
                    "response_time": ping.response_time,
                    "status_code": ping.status_code,
                    "check_timestamp": ping.check_timestamp.isoformat(),
                    "error_message": ping.error_message,
                }
                yield f"event: ping\ndata: {json.dumps(payload)}\n\n"

            # Heartbeat to keep connection alive on idle data
            yield ": heartbeat\n\n"

        response = StreamingHttpResponse(
            event_stream(), content_type="text/event-stream"
        )
        response["Cache-Control"] = "no-cache"
        return response


class OrganizationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrganizationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Organization.objects.filter(id__in=_organization_ids(self.request.user))


class MembershipViewSet(viewsets.ModelViewSet):
    serializer_class = MembershipSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Membership.objects.filter(
            organization_id__in=_organization_ids(self.request.user)
        )

    def perform_create(self, serializer):
        org = serializer.validated_data.get("organization")
        if org.id not in _organization_ids(self.request.user):
            raise PermissionDenied("Organization not allowed")
        if not _is_org_admin(self.request.user, org):
            raise PermissionDenied("Only admins can add members")
        serializer.save()


class BillingView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        org = _ensure_default_org(request.user)
        account = getattr(org, "billing_account", None)
        data = {
            "organization": org.id,
            "plan": account.plan.name if account and account.plan else None,
            "sms_credits": account.sms_credits if account else 0,
            "email_credits": account.email_credits if account else 0,
        }
        return Response(data)

    def post(self, request):
        org = _ensure_default_org(request.user)
        if not _is_org_admin(request.user, org):
            raise PermissionDenied("Only admins can manage billing")
        account = getattr(org, "billing_account", None)
        if not account:
            account = UserAccount.objects.create(organization=org)

        action = request.data.get("action")
        if action == "purchase_credits":
            sms = int(request.data.get("sms", 0))
            emails = int(request.data.get("emails", 0))
            account.sms_credits += max(sms, 0)
            account.email_credits += max(emails, 0)
            account.save(update_fields=["sms_credits", "email_credits", "updated_at"])
            return Response(
                {
                    "sms_credits": account.sms_credits,
                    "email_credits": account.email_credits,
                }
            )

        if action == "change_plan":
            plan_name = request.data.get("plan")
            try:
                plan = Plan.objects.get(name=plan_name)
            except Plan.DoesNotExist:
                return Response(
                    {"detail": "Plan not found"}, status=drf_status.HTTP_400_BAD_REQUEST
                )
            account.plan = plan
            account.save(update_fields=["plan", "updated_at"])
            return Response({"plan": plan.name})

        return Response(
            {"detail": "Invalid action"}, status=drf_status.HTTP_400_BAD_REQUEST
        )
