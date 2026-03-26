from __future__ import annotations

from mlhubspawner.form_builder import JupyterFormBuilder
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


def test_form_builder_captures_ssh_gateway_password() -> None:
    form_builder = JupyterFormBuilder()

    options = form_builder.get_form_options(
        {
            "machineSelect": ["0"],
            "sharedAccessValue": ["true"],
            "machineInstanceId": ["gpu-node:22"],
            "sshGatewayPassword": ["OnlyLettersPasswordOnlyLettersAB"],
        }
    )

    assert options["sshGatewayPassword"] == "OnlyLettersPasswordOnlyLettersAB"


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
