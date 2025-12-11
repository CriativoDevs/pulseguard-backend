import json
import unittest
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from monitoring.models import (
    Membership,
    NotificationConfig,
    Organization,
    Server,
    ServerStatus,
)
from monitoring.services.notification_service import NotificationService

User = get_user_model()


class NotificationServiceTests(TestCase):
    """Test NotificationService functionality."""

    def setUp(self):
        self.server = Server.objects.create(
            name="Test Server",
            host="example.com",
            protocol="https",
            check_interval=300,
            status="active",
        )
        self.status_obj = ServerStatus.objects.create(
            server=self.server,
            status="down",
            consecutive_failures=3,
        )
        # Create email notification config (without triggering auto_now)
        from django.utils import timezone
        from datetime import timedelta

        past_time = timezone.now() - timedelta(
            hours=1
        )  # Set to past to avoid rate limiting

        self.email_config = NotificationConfig(
            server=self.server,
            notification_type="email",
            recipient="test@example.com",
            enabled=True,
        )
        self.email_config.save()
        # Manually update to past time to avoid rate limiting
        NotificationConfig.objects.filter(id=self.email_config.id).update(updated_at=past_time)  # type: ignore[attr-defined]
        self.email_config.refresh_from_db()

        # Create SMS notification config
        self.sms_config = NotificationConfig(
            server=self.server,
            notification_type="sms",
            recipient="+15551234567",
            enabled=True,
        )
        self.sms_config.save()
        NotificationConfig.objects.filter(id=self.sms_config.id).update(updated_at=past_time)  # type: ignore[attr-defined]
        self.sms_config.refresh_from_db()

        self.service = NotificationService()

    @patch("monitoring.services.notification_service.send_mail")
    def test_send_email_on_failure(self, mock_send_mail):
        """Test email notification sent when server goes down."""
        with self.settings(EMAIL_NOTIFICATIONS_ENABLED=True):
            # Create service after settings are applied
            service = NotificationService()
            service.notify_status_change(self.server, self.status_obj, "up")

            mock_send_mail.assert_called_once()
            args, kwargs = mock_send_mail.call_args
            self.assertIn("Test Server", kwargs["subject"])  # Subject
            self.assertIn("DOWN", kwargs["subject"])
            self.assertEqual(kwargs["recipient_list"], ["test@example.com"])

    @patch("monitoring.services.notification_service.send_mail")
    def test_send_email_on_recovery(self, mock_send_mail):
        """Test email notification sent when server recovers."""
        self.status_obj.status = "up"
        with self.settings(EMAIL_NOTIFICATIONS_ENABLED=True):
            service = NotificationService()
            service.notify_status_change(self.server, self.status_obj, "down")

            mock_send_mail.assert_called_once()
            args, kwargs = mock_send_mail.call_args
            self.assertIn("Test Server", kwargs["subject"])
            self.assertIn("RECOVERED", kwargs["subject"])

    @unittest.skip("Skipping SMS test - requires twilio package")
    def test_send_sms_on_failure(self):
        """Test SMS notification sent via Twilio."""
        pass

    @patch("requests.post")
    def test_send_webhook(self, mock_post):
        """Test webhook notification."""
        from django.utils import timezone
        from datetime import timedelta

        past_time = timezone.now() - timedelta(hours=1)
        webhook_config = NotificationConfig(
            server=self.server,
            notification_type="webhook",
            recipient="https://hooks.example.com/webhook",
            enabled=True,
        )
        webhook_config.save()
        NotificationConfig.objects.filter(id=webhook_config.id).update(updated_at=past_time)  # type: ignore[attr-defined]
        webhook_config.refresh_from_db()

        self.service.notify_status_change(self.server, self.status_obj, "up")

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertEqual(call_args[0][0], "https://hooks.example.com/webhook")

        payload = call_args[1]["json"]
        self.assertEqual(payload["server_name"], "Test Server")
        self.assertEqual(payload["new_status"], "down")
        self.assertEqual(payload["old_status"], "up")

    def test_rate_limiting(self):
        """Test notifications are rate limited."""
        with patch("monitoring.services.notification_service.send_mail") as mock_mail:
            with self.settings(EMAIL_NOTIFICATIONS_ENABLED=True):
                service = NotificationService()
                # First notification should send
                service.notify_status_change(self.server, self.status_obj, "up")
                self.assertEqual(mock_mail.call_count, 1)

                # Immediate second notification should be skipped (rate limited)
                # Manually set updated_at to now to simulate recent notification
                from django.utils import timezone

                NotificationConfig.objects.filter(server=self.server).update(
                    updated_at=timezone.now()
                )

                service.notify_status_change(self.server, self.status_obj, "up")
                # Should still be 1 because second call was rate limited
                self.assertEqual(mock_mail.call_count, 1)

    def test_no_notification_if_disabled(self):
        """Test no notification sent if disabled in config."""
        # Disable all notification configs
        self.email_config.enabled = False  # type: ignore[attr-defined]
        self.email_config.save()
        self.sms_config.enabled = False  # type: ignore[attr-defined]
        self.sms_config.save()

        with patch("monitoring.services.notification_service.send_mail") as mock_mail:
            with self.settings(EMAIL_NOTIFICATIONS_ENABLED=True):
                service = NotificationService()
                service.notify_status_change(self.server, self.status_obj, "up")
                mock_mail.assert_not_called()


class MetricsEndpointTests(TestCase):
    """Test metrics API endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="testuser", password="testpass123"
        )
        self.org = Organization.objects.create(name="metrics-org", owner=self.user)
        Membership.objects.create(user=self.user, organization=self.org, role="owner")
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        # Create test data
        self.server1 = Server.objects.create(
            name="Server 1",
            host="example1.com",
            protocol="https",
            check_interval=300,
            status="active",
            owner=self.user,
            organization=self.org,
        )
        self.server2 = Server.objects.create(
            name="Server 2",
            host="example2.com",
            protocol="https",
            check_interval=300,
            status="active",
            owner=self.user,
            organization=self.org,
        )
        ServerStatus.objects.create(server=self.server1, status="up")
        ServerStatus.objects.create(server=self.server2, status="down")

    def test_metrics_overview(self):
        """Test metrics overview endpoint."""
        url = reverse("metrics-overview")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data  # type: ignore[attr-defined]
        self.assertIn("servers", data)
        self.assertEqual(data["servers"]["total"], 2)
        self.assertEqual(data["servers"]["active"], 2)

    def test_uptime_metrics(self):
        """Test uptime metrics endpoint."""
        url = reverse("metrics-uptime")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data  # type: ignore[attr-defined]
        self.assertIn("servers", data)
        self.assertEqual(len(data["servers"]), 2)

    def test_response_times_metrics(self):
        """Test response times metrics endpoint."""
        url = reverse("metrics-response-times")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data  # type: ignore[attr-defined]
        self.assertIn("overall", data)
        self.assertIn("by_server", data)

    def test_failures_metrics(self):
        """Test failures metrics endpoint."""
        url = reverse("metrics-failures")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data  # type: ignore[attr-defined]
        self.assertIn("total_failures", data)
        self.assertIn("by_type", data)
        self.assertIn("recent_failures", data)
