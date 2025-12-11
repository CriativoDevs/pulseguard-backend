import asyncio
from typing import Any, Dict, List, Optional

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model

from .models import PingResult, Server, ServerStatus
from .serializers import PingResultSerializer, ServerStatusSerializer

User = get_user_model()


class StatusConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self) -> None:
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return
        self.user = user
        self._groups: List[str] = []
        await self.accept()

    async def receive_json(  # type: ignore[override]
        self, content: Dict[str, Any], **kwargs: Any
    ) -> None:
        action = content.get("action")
        if action == "latest":
            await self.send_latest(content)
        elif action == "subscribe":
            await self.subscribe(content)
        else:
            await self.send_json({"error": "unknown action"})

    async def disconnect(self, code: int) -> None:  # type: ignore[override]
        for group in self._groups:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def send_latest(self, content: Dict[str, Any]) -> None:
        servers = await self._filter_servers(content)
        limit = int(content.get("limit") or 20)
        statuses = await self._fetch_statuses(servers)
        pings = await self._fetch_recent_pings(servers, limit)
        await self.send_json({"type": "latest", "statuses": statuses, "pings": pings})

    async def subscribe(self, content: Dict[str, Any]) -> None:
        servers = await self._filter_servers(content)
        groups = [self._group_name(server.id) for server in servers]  # type: ignore[attr-defined]
        self._groups = groups
        for group in groups:
            await self.channel_layer.group_add(group, self.channel_name)
        await self.send_json({"type": "subscribed", "servers": [s.id for s in servers]})  # type: ignore[attr-defined]

    async def ping_update(self, event: Dict[str, Any]) -> None:
        await self.send_json(
            {"type": "update", "ping": event["ping"], "status": event["status"]}
        )

    async def _filter_servers(self, content: Dict[str, Any]) -> List[Server]:
        server_ids = content.get("server_ids")
        query = content.get("query")
        return await self._get_servers(server_ids, query)

    @database_sync_to_async
    def _get_servers(
        self, server_ids: Optional[List[int]], query: Optional[str]
    ) -> List[Server]:
        qs = Server.objects.all()
        if server_ids:
            qs = qs.filter(id__in=server_ids)
        if query:
            qs = qs.filter(name__icontains=query)
        return list(qs.order_by("id"))

    @database_sync_to_async
    def _fetch_statuses(self, servers: List[Server]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for server in servers:
            status = (
                ServerStatus.objects.filter(server=server)
                .order_by("-updated_at")
                .first()
            )
            if status:
                results.append(ServerStatusSerializer(status).data)  # type: ignore[arg-type]
        return results

    @database_sync_to_async
    def _fetch_recent_pings(
        self, servers: List[Server], limit: int
    ) -> List[Dict[str, Any]]:
        pings: List[Dict[str, Any]] = []
        for server in servers:
            latest = PingResult.objects.filter(server=server).order_by(
                "-check_timestamp"
            )[:limit]
            pings.extend(PingResultSerializer(latest, many=True).data)
        return pings

    @staticmethod
    def _group_name(server_id: int) -> str:
        return f"server_{server_id}"


def notify_subscribers(ping: PingResult, status: ServerStatus) -> None:
    group = StatusConsumer._group_name(ping.server_id)  # type: ignore[attr-defined]
    payload = {
        "type": "ping_update",
        "ping": PingResultSerializer(ping).data,
        "status": ServerStatusSerializer(status).data,
    }
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        loop.create_task(_group_send(group, payload))
    else:
        async_to_sync(_group_send)(group, payload)


async def _group_send(group: str, payload: Dict[str, Any]) -> None:
    from channels.layers import get_channel_layer

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    await channel_layer.group_send(group, payload)
