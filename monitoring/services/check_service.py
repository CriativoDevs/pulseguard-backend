import socket
import time
from typing import Dict

import requests

from monitoring.models import Server


class HealthCheckService:
    """Performs health checks for servers using protocol-aware strategies."""

    def __init__(self, default_timeout: int = 5):
        self.default_timeout = default_timeout

    def run_check(self, server: Server) -> Dict[str, object]:
        if server.protocol in ("http", "https"):
            return self._check_http(server)
        if server.protocol == "tcp":
            return self._check_tcp(server)
        if server.protocol == "icmp":
            # Simplified ICMP placeholder; production should use a proper ping library
            return self._check_tcp(server)
        return {
            "status": "error",
            "status_code": None,
            "response_time": None,
            "error_message": f"unsupported protocol: {server.protocol}",
        }

    def _check_http(self, server: Server) -> Dict[str, object]:
        url = server.full_url
        timeout = server.timeout or self.default_timeout
        start = time.monotonic()
        try:
            response = requests.get(url, timeout=timeout)
            elapsed_ms = (time.monotonic() - start) * 1000
            status = "success" if response.status_code < 500 else "failure"
            return {
                "status": status,
                "status_code": response.status_code,
                "response_time": round(elapsed_ms, 2),
                "error_message": "",
            }
        except requests.Timeout:
            return {
                "status": "timeout",
                "status_code": None,
                "response_time": None,
                "error_message": "timeout",
            }
        except Exception as exc:  # pragma: no cover - generic fallback path
            return {
                "status": "error",
                "status_code": None,
                "response_time": None,
                "error_message": str(exc),
            }

    def _check_tcp(self, server: Server) -> Dict[str, object]:
        timeout = server.timeout or self.default_timeout
        start = time.monotonic()
        try:
            with socket.create_connection((server.host, server.port), timeout=timeout):
                elapsed_ms = (time.monotonic() - start) * 1000
                return {
                    "status": "success",
                    "status_code": None,
                    "response_time": round(elapsed_ms, 2),
                    "error_message": "",
                }
        except socket.timeout:
            return {
                "status": "timeout",
                "status_code": None,
                "response_time": None,
                "error_message": "timeout",
            }
        except OSError as exc:
            return {
                "status": "failure",
                "status_code": None,
                "response_time": None,
                "error_message": str(exc),
            }
