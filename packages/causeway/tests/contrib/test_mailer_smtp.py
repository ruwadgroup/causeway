from __future__ import annotations

import types
from email.message import EmailMessage
from typing import Any

import pytest

import causeway.plugins as plugin_registry
from causeway.contrib.smtp import SmtpMailer, plugin


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    plugin_registry.clear()


@pytest.fixture
def captured_send(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_send(msg: EmailMessage, **kwargs: Any) -> tuple[dict[str, Any], str]:
        calls.append({"msg": msg, **kwargs})
        return ({}, "ok")

    monkeypatch.setattr("causeway.contrib.smtp.aiosmtplib.send", fake_send)
    return calls


async def test_lifecycle_methods() -> None:
    m = SmtpMailer(host="smtp.example", port=465, starttls=False)
    await m.startup(None)
    await m.shutdown()
    assert await m.ready() is True


async def test_send_builds_message_and_dispatches(
    captured_send: list[dict[str, Any]],
) -> None:
    m = SmtpMailer(
        host="smtp.example",
        port=2525,
        username="u",
        password="p",
        starttls=False,
        sender="from@x",
    )
    await m.send(to="to@y", subject="hi", body="payload")

    assert len(captured_send) == 1
    call = captured_send[0]
    msg = call["msg"]
    assert msg["To"] == "to@y"
    assert msg["From"] == "from@x"
    assert msg["Subject"] == "hi"
    assert msg.get_content().strip() == "payload"
    assert call["hostname"] == "smtp.example"
    assert call["port"] == 2525
    assert call["username"] == "u"
    assert call["password"] == "p"
    assert call["start_tls"] is False


async def test_send_template_renders_str_format(
    captured_send: list[dict[str, Any]],
) -> None:
    m = SmtpMailer(host="smtp.example")
    await m.send_template(
        to="ada@x",
        template="Hello {name}, you have {n} messages.",
        data={"name": "ada", "n": 3},
    )
    msg = captured_send[0]["msg"]
    assert msg.get_content().strip() == "Hello ada, you have 3 messages."


async def test_verify_address_basic_check() -> None:
    m = SmtpMailer(host="smtp.example")
    assert await m.verify_address("a@b") is True
    assert await m.verify_address("nope") is False


def test_plugin_no_op_without_host() -> None:
    plugin(types.SimpleNamespace())
    assert plugin_registry.registered() == []


def test_plugin_reads_settings() -> None:
    plugin(
        types.SimpleNamespace(
            smtp_host="smtp.example",
            smtp_port=2525,
            smtp_user="u",
            smtp_password="p",
            smtp_sender="from@x",
        ),
    )
    [adapter] = plugin_registry.registered()
    assert isinstance(adapter, SmtpMailer)
    assert adapter.host == "smtp.example"
    assert adapter.port == 2525
    assert adapter.sender == "from@x"
