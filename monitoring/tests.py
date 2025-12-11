import socket
from unittest import mock
from io import StringIO
from datetime import timedelta
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from channels.testing import WebsocketCommunicator
from asgiref.sync import async_to_sync

from core.asgi import application
from monitoring.consumers import notify_subscribers

from .models import (
    Membership,
    NotificationConfig,
    Organization,
    PingResult,
    Server,
    ServerStatus,
)
from .tasks.check_runner import run_all_checks
from .services.check_service import HealthCheckService
from .tasks.scheduler import build_scheduler


class CheckCommandTests(TestCase):
    @mock.patch("monitoring.management.commands.check_servers.run_all_checks")
    def test_management_command_runs(self, mock_run):
        mock_run.return_value = [(1, "success"), (2, "failure")]

        from django.core.management import call_command

        out = StringIO()
        call_command("check_servers", stdout=out)
        output = out.getvalue()

        mock_run.assert_called_once()
        self.assertIn("Ran 2 checks", output)


class HealthCheckServiceTests(TestCase):
    def setUp(self):
        self.server_http = Server.objects.create(
            name="http-target",
            protocol="https",
            host="example.com",
            port=443,
            path="/health",
            check_interval=30,
            timeout=5,
        )
        self.server_tcp = Server.objects.create(
            name="tcp-target",
            protocol="tcp",
            host="127.0.0.1",
            port=5432,
            check_interval=30,
            timeout=2,
        )

    @mock.patch("monitoring.services.check_service.requests.get")
    def test_check_http_success(self, mock_get):
        mock_resp = mock.Mock(status_code=200)
        mock_get.return_value = mock_resp

        svc = HealthCheckService()
        result = svc.run_check(self.server_http)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["status_code"], 200)

    @mock.patch(
        "monitoring.services.check_service.requests.get", side_effect=Exception("boom")
    )
    def test_check_http_error(self, mock_get):
        svc = HealthCheckService()
        result = svc.run_check(self.server_http)
        self.assertEqual(result["status"], "error")
        self.assertIn("boom", result["error_message"])

    @mock.patch("monitoring.services.check_service.socket.create_connection")
    def test_check_tcp_success(self, mock_conn):
        mock_conn.return_value.__enter__.return_value = None
        svc = HealthCheckService()
        result = svc.run_check(self.server_tcp)
        self.assertEqual(result["status"], "success")

    @mock.patch(
        "monitoring.services.check_service.socket.create_connection",
        side_effect=socket.timeout,
    )
    def test_check_tcp_timeout(self, mock_conn):
        svc = HealthCheckService()
        result = svc.run_check(self.server_tcp)
        self.assertEqual(result["status"], "timeout")


@override_settings(
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
)
class MonitoringAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="tester", email="tester@example.com", password="pass1234"
        )
        self.org = Organization.objects.create(name="org-main", owner=self.user)
        Membership.objects.create(user=self.user, organization=self.org, role="member")
        self.client.force_authenticate(self.user)

        self.server = Server.objects.create(
            name="api-server",
            protocol="https",
            host="example.com",
            port=443,
            path="/health",
            check_interval=60,
            timeout=5,
            status="active",
            tags="prod,api",
            owner=self.user,
            organization=self.org,
        )

        self.status_obj = ServerStatus.objects.create(
            server=self.server,
            status="up",
            uptime_percentage=99.9,
            last_check=timezone.now(),
            last_up=timezone.now(),
            last_down=None,
            consecutive_failures=0,
            failure_threshold=3,
            message="OK",
        )

        self.ping_result = PingResult.objects.create(
            server=self.server,
            status="success",
            response_time=120.5,
            status_code=200,
            error_message="",
            check_timestamp=timezone.now(),
        )

        self.notification = NotificationConfig.objects.create(
            server=self.server,
            notification_type="email",
            recipient="ops@example.com",
            enabled=True,
            notify_on_failure=True,
            notify_on_recovery=True,
            min_notification_interval=300,
        )

    def test_server_serializer_full_url(self):
        url = reverse("server-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        first = response.data["results"][0]  # type: ignore[attr-defined]
        self.assertEqual(first["full_url"], "https://example.com:443/health")

    def test_create_server(self):
        url = reverse("server-list")
        payload = {
            "name": "worker",
            "protocol": "http",
            "host": "worker.local",
            "port": 80,
            "path": "/status",
            "check_interval": 120,
            "timeout": 10,
            "status": "active",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Server.objects.count(), 2)

    def test_ping_results_readonly(self):
        list_url = reverse("pingresult-list")
        response = self.client.get(list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"][0]["status"], "success")  # type: ignore[attr-defined]

        create_resp = self.client.post(
            list_url, {"server": self.server.id, "status": "failure"}
        )
        self.assertEqual(create_resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_server_status_readonly(self):
        list_url = reverse("serverstatus-list")
        response = self.client.get(list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        detail_url = reverse("serverstatus-detail", args=[self.status_obj.id])
        detail_resp = self.client.get(detail_url)
        self.assertEqual(detail_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_resp.data["status"], "up")  # type: ignore[attr-defined]

    def test_notification_config_crud(self):
        list_url = reverse("notificationconfig-list")
        payload = {
            "server": self.server.id,
            "notification_type": "email",
            "recipient": "alerts@example.com",
            "enabled": True,
            "notify_on_failure": True,
            "notify_on_recovery": False,
            "min_notification_interval": 600,
        }
        create_resp = self.client.post(list_url, payload, format="json")
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)

        detail_url = reverse("notificationconfig-detail", args=[create_resp.data["id"]])  # type: ignore[attr-defined]
        patch_resp = self.client.patch(detail_url, {"enabled": False}, format="json")
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_resp.data["enabled"], False)  # type: ignore[attr-defined]

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        url = reverse("server-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_run_checks_endpoint_requires_admin(self):
        url = reverse("run-checks")
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_run_checks_endpoint_runs(self):
        self.user.is_staff = True
        self.user.save()

        url = reverse("run-checks")
        with mock.patch(
            "monitoring.tasks.check_runner.run_all_checks",
            return_value=[(self.server.id, "success")],
        ):
            resp = self.client.post(url)

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)  # type: ignore[attr-defined]

    def test_status_stream_endpoint(self):
        url = reverse("status-stream")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp["Content-Type"], "text/event-stream")
        # Consume first chunk
        body = b"".join(list(resp.streaming_content))
        self.assertIn(b"data: ", body)
        self.assertIn(b"retry: 5000", body)
        self.assertIn(b": heartbeat", body)
        self.assertIn(b"event: status", body)
        self.assertIn(b"event: ping", body)

    def test_status_stream_filter_by_status(self):
        url = reverse("status-stream") + "?status=up"
        resp = self.client.get(url)
        body = b"".join(list(resp.streaming_content))
        self.assertIn(b"api-server", body)

    def test_status_stream_since_filters_old(self):
        future = (timezone.now() + timedelta(hours=1)).isoformat()
        encoded = quote(future)
        url = reverse("status-stream") + f"?since={encoded}"
        resp = self.client.get(url)
        body = b"".join(list(resp.streaming_content))
        self.assertNotIn(b"event: status", body)
        self.assertNotIn(b"event: ping", body)
        self.assertIn(b"retry: 5000", body)


@override_settings(
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
)
class CheckRunnerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="runner-user", email="runner@example.com", password="pass1234"
        )
        self.org = Organization.objects.create(name="org-runner", owner=self.user)
        Membership.objects.create(user=self.user, organization=self.org, role="owner")
        self.server = Server.objects.create(
            name="runner",
            protocol="https",
            host="example.com",
            port=443,
            path="/health",
            check_interval=60,
            timeout=5,
            owner=self.user,
            organization=self.org,
        )

    def test_run_all_checks_success_updates_status(self):
        class FakeService:
            def run_check(self, server):
                return {
                    "status": "success",
                    "status_code": 200,
                    "response_time": 50,
                    "error_message": "",
                }

        run_all_checks(
            service=FakeService(), now=timezone.now(), queryset=[self.server]
        )

        self.assertEqual(PingResult.objects.count(), 1)
        status_obj = ServerStatus.objects.get(server=self.server)
        self.assertEqual(status_obj.status, "up")
        self.assertEqual(status_obj.consecutive_failures, 0)

    def test_run_all_checks_failure_marks_down(self):
        ServerStatus.objects.create(
            server=self.server, failure_threshold=1, status="up"
        )

        class FakeService:
            def run_check(self, server):
                return {
                    "status": "failure",
                    "status_code": None,
                    "response_time": None,
                    "error_message": "connection refused",
                }

        run_all_checks(
            service=FakeService(), now=timezone.now(), queryset=[self.server]
        )

        status_obj = ServerStatus.objects.get(server=self.server)
        self.assertEqual(status_obj.status, "down")
        self.assertEqual(status_obj.consecutive_failures, 1)


class SchedulerTests(TestCase):
    @mock.patch("monitoring.tasks.scheduler.BackgroundScheduler")
    def test_scheduler_adds_job(self, mock_sched_cls):
        mock_sched = mock_sched_cls.return_value

        sched = build_scheduler(interval_seconds=120)

        mock_sched_cls.assert_called_once()
        mock_sched.add_job.assert_called_once()
        args, kwargs = mock_sched.add_job.call_args
        self.assertEqual(kwargs["seconds"], 120)
        self.assertEqual(kwargs["id"], "run_all_checks")
        self.assertEqual(sched, mock_sched)


class SchedulerCommandTests(TestCase):
    @mock.patch("monitoring.management.commands.start_scheduler.build_scheduler")
    def test_start_scheduler_no_loop(self, mock_build):
        mock_sched = mock.Mock()
        mock_build.return_value = mock_sched

        from django.core.management import call_command

        out = StringIO()
        call_command("start_scheduler", "--interval", "120", "--no-loop", stdout=out)

        mock_build.assert_called_once_with(interval_seconds=120)
        mock_sched.start.assert_called_once()
        mock_sched.shutdown.assert_called_once_with(wait=False)
        self.assertIn("Scheduler started", out.getvalue())


@override_settings(
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
)
class StatusConsumerTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="wsuser", email="ws@example.com", password="pass1234"
        )
        self.org = Organization.objects.create(name="org-ws", owner=self.user)
        Membership.objects.create(user=self.user, organization=self.org, role="owner")
        self.server = Server.objects.create(
            name="ws-server",
            protocol="https",
            host="example.com",
            port=443,
            path="/health",
            check_interval=30,
            timeout=5,
            owner=self.user,
            organization=self.org,
        )
        self.status_obj = ServerStatus.objects.create(
            server=self.server,
            status="up",
            uptime_percentage=99.0,
            last_check=timezone.now(),
            message="OK",
        )
        self.ping = PingResult.objects.create(
            server=self.server,
            status="success",
            response_time=100,
            status_code=200,
            error_message="",
            check_timestamp=timezone.now(),
        )

    def test_rejects_anonymous(self):
        async def run():
            communicator = WebsocketCommunicator(application, "/ws/status/")
            communicator.scope["user"] = AnonymousUser()
            connected, _ = await communicator.connect()
            self.assertFalse(connected)

        async_to_sync(run)()

    def test_latest_payload(self):
        async def run():
            communicator = WebsocketCommunicator(application, "/ws/status/")
            communicator.scope["user"] = self.user
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            await communicator.send_json_to(
                {"action": "latest", "server_ids": [self.server.id], "limit": 5}
            )
            message = await communicator.receive_json_from()
            self.assertEqual(message["type"], "latest")
            self.assertEqual(message["statuses"][0]["server"], self.server.id)
            await communicator.disconnect()

        async_to_sync(run)()

    def test_subscribe_and_receive_update(self):
        async def run():
            communicator = WebsocketCommunicator(application, "/ws/status/")
            communicator.scope["user"] = self.user
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            await communicator.send_json_to(
                {"action": "subscribe", "server_ids": [self.server.id]}
            )
            sub_msg = await communicator.receive_json_from()
            self.assertEqual(sub_msg["type"], "subscribed")

            notify_subscribers(self.ping, self.status_obj)
            update_msg = await communicator.receive_json_from()
            self.assertEqual(update_msg["type"], "update")
            self.assertEqual(update_msg["ping"]["server"], self.server.id)
            await communicator.disconnect()

        async_to_sync(run)()
