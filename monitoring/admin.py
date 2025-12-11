from django.contrib import admin
from .models import Server, PingResult, ServerStatus, NotificationConfig


@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "protocol",
        "host",
        "port",
        "status",
        "check_interval",
        "created_at",
    ]
    list_filter = ["status", "protocol", "created_at"]
    search_fields = ["name", "host", "description"]
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = (
        ("Basic Info", {"fields": ("name", "description", "status")}),
        ("Connection", {"fields": ("protocol", "host", "port", "path")}),
        ("Monitoring", {"fields": ("check_interval", "timeout", "tags")}),
        ("Notifications", {"fields": ("notify_on_failure", "notify_recovery")}),
        (
            "Metadata",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )


@admin.register(PingResult)
class PingResultAdmin(admin.ModelAdmin):
    list_display = [
        "server",
        "status",
        "response_time",
        "status_code",
        "check_timestamp",
    ]
    list_filter = ["status", "check_timestamp", "server"]
    search_fields = ["server__name", "error_message"]
    readonly_fields = ["created_at", "updated_at"]
    date_hierarchy = "check_timestamp"


@admin.register(ServerStatus)
class ServerStatusAdmin(admin.ModelAdmin):
    list_display = [
        "server",
        "status",
        "uptime_percentage",
        "last_check",
        "consecutive_failures",
    ]
    list_filter = ["status", "updated_at"]
    search_fields = ["server__name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(NotificationConfig)
class NotificationConfigAdmin(admin.ModelAdmin):
    list_display = ["server", "notification_type", "recipient", "enabled"]
    list_filter = ["notification_type", "enabled", "created_at"]
    search_fields = ["server__name", "recipient"]
    readonly_fields = ["created_at", "updated_at"]
