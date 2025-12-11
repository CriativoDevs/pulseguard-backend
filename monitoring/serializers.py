from rest_framework import serializers

from .models import (
    Membership,
    NotificationConfig,
    Organization,
    PingResult,
    Server,
    ServerStatus,
)


class ServerSerializer(serializers.ModelSerializer):
    full_url = serializers.SerializerMethodField(read_only=True)
    organization = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Server
        fields = [
            "id",
            "organization",
            "name",
            "description",
            "protocol",
            "host",
            "port",
            "path",
            "check_interval",
            "timeout",
            "status",
            "tags",
            "notify_on_failure",
            "notify_recovery",
            "full_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at", "full_url", "organization"]

    def get_full_url(self, obj):
        return obj.full_url


class PingResultSerializer(serializers.ModelSerializer):
    server_name = serializers.ReadOnlyField(source="server.name")

    class Meta:
        model = PingResult
        fields = [
            "id",
            "server",
            "server_name",
            "status",
            "response_time",
            "status_code",
            "error_message",
            "check_timestamp",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at", "server_name"]


class ServerStatusSerializer(serializers.ModelSerializer):
    server_name = serializers.ReadOnlyField(source="server.name")

    class Meta:
        model = ServerStatus
        fields = [
            "id",
            "server",
            "server_name",
            "status",
            "uptime_percentage",
            "last_check",
            "last_up",
            "last_down",
            "consecutive_failures",
            "failure_threshold",
            "message",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at", "server_name"]


class NotificationConfigSerializer(serializers.ModelSerializer):
    server_name = serializers.ReadOnlyField(source="server.name")

    class Meta:
        model = NotificationConfig
        fields = [
            "id",
            "server",
            "server_name",
            "notification_type",
            "recipient",
            "enabled",
            "notify_on_failure",
            "notify_on_recovery",
            "min_notification_interval",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at", "server_name"]


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "plan", "locale", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class MembershipSerializer(serializers.ModelSerializer):
    organization_name = serializers.ReadOnlyField(source="organization.name")
    user_email = serializers.ReadOnlyField(source="user.email")

    class Meta:
        model = Membership
        fields = [
            "id",
            "user",
            "user_email",
            "organization",
            "organization_name",
            "role",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "created_at",
            "updated_at",
            "user_email",
            "organization_name",
        ]
