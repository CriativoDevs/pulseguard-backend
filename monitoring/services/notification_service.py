"""Notification service for sending alerts via email and SMS"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from monitoring.models import NotificationConfig, Server, ServerStatus, UserAccount

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending notifications via multiple channels"""

    def __init__(self):
        self.email_enabled = getattr(settings, "EMAIL_NOTIFICATIONS_ENABLED", True)
        self.sms_enabled = getattr(settings, "SMS_NOTIFICATIONS_ENABLED", False)

    def notify_status_change(
        self,
        server: Server,
        status: ServerStatus,
        previous_status: Optional[str] = None,
    ) -> None:
        """Send notifications when server status changes"""
        # Skip if no status change
        if previous_status and previous_status == status.status:
            return

        # Determine notification type
        is_failure = status.status in ["down", "degraded"]
        is_recovery = previous_status in ["down", "degraded"] and status.status == "up"

        if not is_failure and not is_recovery:
            return

        # Get active notification configs
        configs = NotificationConfig.objects.filter(
            server=server,
            enabled=True,
        )

        if is_failure:
            configs = configs.filter(notify_on_failure=True)
        elif is_recovery:
            configs = configs.filter(notify_on_recovery=True)

        for config in configs:
            # Check rate limiting
            if not self._can_send_notification(config):
                logger.info(
                    f"Skipping notification for {server.name} to {config.recipient} - rate limited"
                )
                continue

            # Send based on type
            if config.notification_type == "email":
                self._send_email(server, status, config, is_recovery)
            elif config.notification_type == "sms":
                self._send_sms(server, status, config, is_recovery)
            elif config.notification_type == "webhook":
                self._send_webhook(server, status, config, is_recovery, previous_status)

    def _can_send_notification(self, config: NotificationConfig) -> bool:
        """Check if notification can be sent based on rate limiting"""
        # Get last notification from a tracking model (to be implemented)
        # For now, we'll use a simple approach with updated_at
        if not config.updated_at:
            return True

        min_interval = timedelta(seconds=config.min_notification_interval)
        time_since_last = timezone.now() - config.updated_at

        return time_since_last >= min_interval

    def _get_account(self, server: Server) -> Optional[UserAccount]:
        """Return billing account for the server organization or owner."""
        # Prefer organization-level billing if present
        if getattr(server, "organization", None):
            try:
                return server.organization.billing_account  # type: ignore[attr-defined]
            except UserAccount.DoesNotExist:
                pass

        if not hasattr(server, "owner") or server.owner is None:
            return None
        try:
            return server.owner.billing_account  # type: ignore[attr-defined]
        except UserAccount.DoesNotExist:
            return None

    def _send_email(
        self,
        server: Server,
        status: ServerStatus,
        config: NotificationConfig,
        is_recovery: bool,
    ) -> None:
        """Send email notification"""
        if not self.email_enabled:
            logger.warning("Email notifications are disabled in settings")
            return

        account = self._get_account(server)
        if account and account.email_credits <= 0:
            logger.warning(
                "Email not sent for %s - no email credits for owner %s",
                server.name,
                server.owner,
            )
            return

        subject_prefix = "✅ RECOVERED" if is_recovery else "🚨 ALERT"
        subject_status = status.status.upper()
        subject = f"{subject_prefix}: {server.name} {subject_status}"

        status_emoji = {"up": "✅", "down": "🔴", "degraded": "⚠️", "unknown": "❓"}
        emoji = status_emoji.get(status.status, "❓")

        message = f"""
Server Status Alert

Server: {server.name}
Status: {emoji} {status.status.upper()}
URL: {server.full_url}

Details:
- Last Check: {status.last_check.strftime('%Y-%m-%d %H:%M:%S') if status.last_check else 'N/A'}
- Uptime: {status.uptime_percentage:.2f}%
- Consecutive Failures: {status.consecutive_failures}
- Message: {status.message or 'No additional details'}

---
This is an automated message from PulseGuard
"""

        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[config.recipient],
                fail_silently=False,
            )
            logger.info(f"Email sent to {config.recipient} for server {server.name}")
            if account:
                account.consume_email()
            # Update last notification time
            config.updated_at = timezone.now()
            config.save(update_fields=["updated_at"])
        except Exception as e:
            logger.error(f"Failed to send email to {config.recipient}: {e}")

    def _send_sms(
        self,
        server: Server,
        status: ServerStatus,
        config: NotificationConfig,
        is_recovery: bool,
    ) -> None:
        """Send SMS notification using Twilio"""
        if not self.sms_enabled:
            logger.warning("SMS notifications are disabled in settings")
            return

        account = self._get_account(server)
        if account and account.sms_credits <= 0:
            logger.warning(
                "SMS not sent for %s - no SMS credits for owner %s",
                server.name,
                server.owner,
            )
            return

        prefix = "RECOVERED" if is_recovery else "ALERT"
        message = f"{prefix}: {server.name} is {status.status.upper()}. Uptime: {status.uptime_percentage:.1f}%"

        try:
            from twilio.rest import Client  # type: ignore

            account_sid = getattr(settings, "TWILIO_ACCOUNT_SID", None)
            auth_token = getattr(settings, "TWILIO_AUTH_TOKEN", None)
            from_number = getattr(settings, "TWILIO_PHONE_NUMBER", None)

            if not all([account_sid, auth_token, from_number]):
                logger.error("Twilio credentials not configured in settings")
                return

            client = Client(account_sid, auth_token)
            client.messages.create(body=message, from_=from_number, to=config.recipient)

            logger.info(f"SMS sent to {config.recipient} for server {server.name}")
            if account:
                account.consume_sms()
            # Update last notification time
            config.updated_at = timezone.now()
            config.save(update_fields=["updated_at"])
        except ImportError:
            logger.error("Twilio library not installed. Run: pip install twilio")
        except Exception as e:
            logger.error(f"Failed to send SMS to {config.recipient}: {e}")

    def _send_webhook(
        self,
        server: Server,
        status: ServerStatus,
        config: NotificationConfig,
        is_recovery: bool,
        previous_status: Optional[str] = None,
    ) -> None:
        """Send webhook notification"""
        import json

        import requests

        payload = {
            "event": "recovery" if is_recovery else "failure",
            "server_name": server.name,
            "server_url": server.full_url,
            "new_status": status.status,
            "old_status": previous_status,
            "uptime_percentage": status.uptime_percentage,
            "consecutive_failures": status.consecutive_failures,
            "message": status.message,
            "last_check": (
                status.last_check.isoformat() if status.last_check else None
            ),
            "timestamp": timezone.now().isoformat(),
        }

        try:
            response = requests.post(
                config.recipient,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            logger.info(f"Webhook sent to {config.recipient} for server {server.name}")
            # Update last notification time
            config.updated_at = timezone.now()
            config.save(update_fields=["updated_at"])
        except Exception as e:
            logger.error(f"Failed to send webhook to {config.recipient}: {e}")
