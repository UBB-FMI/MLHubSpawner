from __future__ import annotations

import asyncio
import json
import logging
import random
import string
from threading import RLock


PASSWORD_ALPHABET = string.ascii_letters
PASSWORD_LENGTH = 32
_RANDOM = random.SystemRandom()
_PASSWORDS: dict[str, str] = {}
_PASSWORDS_LOCK = RLock()


class SSHGatewayControllerError(RuntimeError):
    """Raised when the SSH gateway control channel fails."""


class SSHGatewayController:
    def __init__(
        self,
        logger: logging.Logger | None,
        *,
        public_host: str,
        public_port: int,
        control_host: str,
        control_port: int,
        shared_secret: str,
        control_timeout: int = 5,
    ):
        self.log = logger or logging.getLogger(__name__)
        self.public_host = public_host
        self.public_port = int(public_port)
        self.control_host = control_host
        self.control_port = int(control_port)
        self.shared_secret = shared_secret
        self.control_timeout = max(1, int(control_timeout))

    def generate_password(self, username: str) -> str:
        password = "".join(_RANDOM.choice(PASSWORD_ALPHABET) for _ in range(PASSWORD_LENGTH))
        self.set_password(username, password)
        return password

    def set_password(self, username: str, password: str) -> str:
        with _PASSWORDS_LOCK:
            _PASSWORDS[username] = password
        return password

    def get_password(self, username: str) -> str | None:
        with _PASSWORDS_LOCK:
            return _PASSWORDS.get(username)

    def clear_password(self, username: str) -> None:
        with _PASSWORDS_LOCK:
            _PASSWORDS.pop(username, None)

    def build_ui_context(self, username: str) -> dict[str, object]:
        password = self.get_password(username) or self.generate_password(username)
        return {
            "username": username,
            "password": password,
            "host": self.public_host or self.control_host,
            "port": self.public_port,
        }

    async def register_session(self, username: str, password: str, upstream_host: str, upstream_port: int) -> None:
        self.set_password(username, password)
        await self._send_request(
            {
                "action": "register",
                "username": username,
                "password": password,
                "upstream_host": upstream_host,
                "upstream_port": int(upstream_port),
            }
        )

    async def unregister_session(self, username: str) -> None:
        self.clear_password(username)
        await self._send_request({"action": "unregister", "username": username})

    async def _send_request(self, payload: dict[str, object]) -> None:
        if not self.control_host:
            raise SSHGatewayControllerError("ssh_gateway_control_host is not configured")
        if not self.shared_secret:
            raise SSHGatewayControllerError("ssh_gateway_shared_secret is not configured")

        message = dict(payload)
        message["secret"] = self.shared_secret
        reader = None
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.control_host, self.control_port),
                timeout=self.control_timeout,
            )
            writer.write((json.dumps(message) + "\n").encode("utf-8"))
            await asyncio.wait_for(writer.drain(), timeout=self.control_timeout)
            raw_response = await asyncio.wait_for(reader.readline(), timeout=self.control_timeout)
        except Exception as exc:
            raise SSHGatewayControllerError(f"failed to reach SSH gateway control channel: {exc}") from exc
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()

        if not raw_response:
            raise SSHGatewayControllerError("SSH gateway control channel returned no response")

        try:
            response = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SSHGatewayControllerError(f"invalid SSH gateway response: {exc}") from exc

        if not isinstance(response, dict) or not response.get("ok"):
            error_message = "unknown error"
            if isinstance(response, dict):
                error_message = str(response.get("error", error_message))
            raise SSHGatewayControllerError(f"SSH gateway request failed: {error_message}")
