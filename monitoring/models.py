from decimal import Decimal

from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    """Base model with timestamp fields"""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Server(TimeStampedModel):
    """Server to be monitored"""

    PROTOCOL_CHOICES = [
        ("http", "HTTP"),
        ("https", "HTTPS"),
        ("icmp", "ICMP/Ping"),
        ("tcp", "TCP"),
    ]

    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("maintenance", "Maintenance"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="servers",
        null=True,
        blank=True,
    )
    organization = models.ForeignKey(
        "Organization",
        on_delete=models.CASCADE,
        related_name="servers",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255, unique=True, db_index=True)
    description = models.TextField(blank=True, null=True)

    # Connection details
    protocol = models.CharField(
        max_length=10, choices=PROTOCOL_CHOICES, default="https"
    )
    host = models.CharField(max_length=255)
    port = models.IntegerField(default=443)
    path = models.CharField(
        max_length=500,
        blank=True,
        default="/",
        help_text="URL path for HTTP/HTTPS checks",
    )

    # Monitoring configuration
    check_interval = models.IntegerField(
        default=300, help_text="Check interval in seconds"
    )
    timeout = models.IntegerField(default=10, help_text="Timeout in seconds")

    # Status
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="active", db_index=True
    )

    # Tags for organization
    tags = models.CharField(
        max_length=500, blank=True, help_text="Comma-separated tags"
    )

    # Notifications
    notify_on_failure = models.BooleanField(default=True)
    notify_recovery = models.BooleanField(default=True)

    class Meta(TimeStampedModel.Meta):  # type: ignore[name-defined]
        ordering = ["name"]
        indexes = [
            models.Index(fields=["status", "updated_at"]),
            models.Index(fields=["protocol", "host"]),
            models.Index(fields=["organization", "status"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.protocol}://{self.host}:{self.port})"

    @property
    def full_url(self):
        """Generate full URL for the server"""
        return f"{self.protocol}://{self.host}:{self.port}{self.path}"


class PingResult(TimeStampedModel):
    """Results of server health checks"""

    STATUS_CHOICES = [
        ("success", "Success"),
        ("failure", "Failure"),
        ("timeout", "Timeout"),
        ("error", "Error"),
    ]

    server = models.ForeignKey(
        Server, on_delete=models.CASCADE, related_name="ping_results", db_index=True
    )

    # Result data
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, db_index=True)
    response_time = models.FloatField(
        null=True, blank=True, help_text="Response time in milliseconds"
    )
    status_code = models.IntegerField(null=True, blank=True)

    # Error details
    error_message = models.TextField(blank=True, null=True)

    # Metadata
    check_timestamp = models.DateTimeField(db_index=True)

    class Meta(TimeStampedModel.Meta):  # type: ignore[name-defined]
        ordering = ["-check_timestamp"]
        indexes = [
            models.Index(fields=["server", "-check_timestamp"]),
            models.Index(fields=["status", "check_timestamp"]),
        ]

    def __str__(self):
        return f"{self.server.name} - {self.status} ({self.check_timestamp})"


class ServerStatus(TimeStampedModel):
    """Current aggregated status of a server"""

    STATUS_CHOICES = [
        ("up", "Up"),
        ("down", "Down"),
        ("degraded", "Degraded"),
        ("unknown", "Unknown"),
    ]

    server = models.OneToOneField(
        Server, on_delete=models.CASCADE, related_name="current_status", db_index=True
    )

    # Current status
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="unknown", db_index=True
    )

    # Metrics
    uptime_percentage = models.FloatField(default=100.0)
    last_check = models.DateTimeField(null=True, blank=True)
    last_up = models.DateTimeField(null=True, blank=True)
    last_down = models.DateTimeField(null=True, blank=True)

    # Consecutive failures
    consecutive_failures = models.IntegerField(default=0)
    failure_threshold = models.IntegerField(
        default=3, help_text="Number of failures before marking as down"
    )

    # Message
    message = models.TextField(blank=True, null=True)

    class Meta(TimeStampedModel.Meta):  # type: ignore[name-defined]
        ordering = ["server__name"]

    def __str__(self):
        return f"{self.server.name} - {self.status}"

    @property
    def is_healthy(self):
        """Check if server is healthy"""
        return self.status == "up"


class NotificationConfig(TimeStampedModel):
    """Notification configuration for servers"""

    NOTIFICATION_TYPE_CHOICES = [
        ("email", "Email"),
        ("webhook", "Webhook"),
        ("sms", "SMS"),
    ]

    server = models.ForeignKey(
        Server, on_delete=models.CASCADE, related_name="notification_configs"
    )
    notification_type = models.CharField(
        max_length=20, choices=NOTIFICATION_TYPE_CHOICES
    )

    # Recipient/destination
    recipient = models.CharField(
        max_length=500, help_text="Email, phone number, or webhook URL"
    )

    # Configuration
    enabled = models.BooleanField(default=True, db_index=True)
    notify_on_failure = models.BooleanField(default=True)
    notify_on_recovery = models.BooleanField(default=True)

    # Rate limiting
    min_notification_interval = models.IntegerField(
        default=300, help_text="Minimum interval between notifications in seconds"
    )

    class Meta(TimeStampedModel.Meta):  # type: ignore[name-defined]
        ordering = ["server", "notification_type"]
        unique_together = ["server", "notification_type", "recipient"]

    def __str__(self):
        return f"{self.server.name} - {self.notification_type} to {self.recipient}"


class Plan(TimeStampedModel):
    """Subscription plan with included notifications."""

    name = models.CharField(max_length=100, unique=True)
    monthly_price = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00")
    )
    included_sms = models.IntegerField(default=0)
    included_emails = models.IntegerField(default=0)
    price_per_extra_sms = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0.00")
    )
    price_per_extra_email = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0.00")
    )

    class Meta(TimeStampedModel.Meta):  # type: ignore[name-defined]
        ordering = ["monthly_price"]

    def __str__(self):
        return f"{self.name} (${self.monthly_price})"


class Organization(TimeStampedModel):
    """Tenant organization with plan and localization."""

    name = models.CharField(max_length=150, unique=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_organizations",
    )
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True)
    locale = models.CharField(
        max_length=8,
        default="en",
        help_text="IETF language tag (e.g. en, pt-BR, es, fr, it, ig)",
    )

    class Meta(TimeStampedModel.Meta):  # type: ignore[name-defined]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Membership(TimeStampedModel):
    """User membership within an organization with a role."""

    ROLE_CHOICES = [
        ("owner", "Owner"),
        ("admin", "Admin"),
        ("member", "Member"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="member")

    class Meta(TimeStampedModel.Meta):  # type: ignore[name-defined]
        unique_together = ("user", "organization")
        ordering = ["organization", "user"]

    def __str__(self):
        return f"{self.user} in {self.organization} ({self.role})"


class UserAccount(TimeStampedModel):
    """Per-user billing account tracking credits and plan."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="billing_account",
        null=True,
        blank=True,
    )
    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name="billing_account",
        null=True,
        blank=True,
    )
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True)
    sms_credits = models.IntegerField(default=0)
    email_credits = models.IntegerField(default=0)

    class Meta(TimeStampedModel.Meta):  # type: ignore[name-defined]
        ordering = ["user"]

    def __str__(self):
        if self.organization:
            return f"Account for {self.organization}"
        return f"Account for {self.user}"

    def consume_sms(self) -> bool:
        """Attempt to consume an SMS credit; return False if unavailable."""
        if self.sms_credits <= 0:
            return False
        self.sms_credits -= 1
        self.save(update_fields=["sms_credits", "updated_at"])
        return True

    def consume_email(self) -> bool:
        """Attempt to consume an email credit; return False if unavailable."""
        if self.email_credits <= 0:
            return False
        self.email_credits -= 1
        self.save(update_fields=["email_credits", "updated_at"])
        return True
