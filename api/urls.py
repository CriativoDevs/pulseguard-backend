from django.urls import include, path
from rest_framework.routers import DefaultRouter

from monitoring.views import (
    BillingView,
    MembershipViewSet,
    NotificationConfigViewSet,
    OrganizationViewSet,
    PingResultViewSet,
    RunChecksView,
    ServerStatusStreamView,
    ServerStatusViewSet,
    ServerViewSet,
)
from monitoring.metrics import MetricsViewSet

router = DefaultRouter()
router.register(r"servers", ServerViewSet, basename="server")
router.register(r"organizations", OrganizationViewSet, basename="organization")
router.register(r"memberships", MembershipViewSet, basename="membership")
router.register(r"ping-results", PingResultViewSet, basename="pingresult")
router.register(r"server-status", ServerStatusViewSet, basename="serverstatus")
router.register(
    r"notification-configs", NotificationConfigViewSet, basename="notificationconfig"
)
router.register(r"metrics", MetricsViewSet, basename="metrics")

urlpatterns = [
    path("", include(router.urls)),
    path("auth/", include("authentication.urls")),
    path("checks/run/", RunChecksView.as_view(), name="run-checks"),
    path("events/status/", ServerStatusStreamView.as_view(), name="status-stream"),
    path("billing/", BillingView.as_view(), name="billing"),
]
