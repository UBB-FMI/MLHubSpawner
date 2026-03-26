from __future__ import annotations

import asyncio

import pytest

from mlhubspawner.form_builder import JupyterFormBuilder
from mlhubspawner.control_crypto import EncryptedControlCodec
from mlhubspawner.ssh_gateway_controller import PASSWORD_LENGTH, SSHGatewayController


def test_generate_password_uses_letters_and_rotates() -> None:
    controller = SSHGatewayController(
        None,
        public_host="gateway.example",
        public_port=2222,
        control_host="gateway.internal",
        control_port=2223,
        shared_secret="secret",
        control_timeout=5,
    )

    first = controller.generate_password("md5_user")
    second = controller.generate_password("md5_user")

    assert len(first) == PASSWORD_LENGTH
    assert len(second) == PASSWORD_LENGTH
    assert first.isalpha()
    assert second.isalpha()
    assert first != second


def test_build_ui_context_falls_back_to_control_host() -> None:
    controller = SSHGatewayController(
        None,
        public_host="",
        public_port=2222,
        control_host="gateway.internal",
        control_port=2223,
        shared_secret="secret",
        control_timeout=5,
    )

    controller.set_password("md5_user", "OnlyLettersPasswordOnlyLettersAB")
    context = controller.build_ui_context("md5_user")

    assert context["username"] == "md5_user"
    assert context["password"] == "OnlyLettersPasswordOnlyLettersAB"
    assert context["host"] == "gateway.internal"
    assert context["port"] == 2222


def test_form_builder_does_not_capture_ssh_gateway_password() -> None:
    form_builder = JupyterFormBuilder()

    options = form_builder.get_form_options(
        {
            "machineSelect": ["0"],
            "sharedAccessValue": ["true"],
            "machineInstanceId": ["gpu-node:22"],
            "sshGatewayPassword": ["OnlyLettersPasswordOnlyLettersAB"],
        }
    )

    assert "sshGatewayPassword" not in options


def test_form_builder_embeds_ssh_gateway_context() -> None:
    form_builder = JupyterFormBuilder()

    html = form_builder.get_html_page(
        [],
        uiContext={
            "sshGateway": {
                "username": "md5_user",
                "password": "OnlyLettersPasswordOnlyLettersAB",
                "host": "gateway.example",
                "port": 2222,
            }
        },
    )

    assert '"sshGateway"' in html
    assert "md5_user" in html
    assert "gateway.example" in html


@pytest.mark.asyncio
async def test_register_session_uses_encrypted_control_payload() -> None:
    codec = EncryptedControlCodec("secret")
    captured: dict[str, object] = {}

    async def handle_client(reader, writer) -> None:
        raw_request = await reader.readline()
        captured["raw_request"] = raw_request
        captured["request"] = codec.decode(raw_request)
        writer.write(codec.encode({"ok": True}))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = int(server.sockets[0].getsockname()[1])

    controller = SSHGatewayController(
        None,
        public_host="gateway.example",
        public_port=2222,
        control_host="127.0.0.1",
        control_port=port,
        shared_secret="secret",
        control_timeout=5,
    )

    try:
        await controller.register_session("md5_user", "OnlyLettersPasswordOnlyLettersAB", "10.0.0.15", 22)
    finally:
        server.close()
        await server.wait_closed()

    raw_request = captured["raw_request"]
    request = captured["request"]

    assert isinstance(raw_request, bytes)
    assert b'"action":"register"' not in raw_request
    assert b'"secret":"secret"' not in raw_request
    assert isinstance(request, dict)
    assert request["action"] == "register"
    assert request["secret"] == "secret"
