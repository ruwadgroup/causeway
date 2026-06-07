"""SMTP mailer for :class:`causeway.contracts.Mailer`."""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any, ClassVar

import aiosmtplib


class SmtpMailer:
    contract_version: ClassVar[str] = "v1.0"

    def __init__(
        self,
        *,
        host: str,
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        starttls: bool = True,
        sender: str = "noreply@localhost",
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.starttls = starttls
        self.sender = sender

    async def startup(self, settings: Any) -> None: ...
    async def shutdown(self) -> None: ...
    async def ready(self) -> bool:
        return True

    async def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        await aiosmtplib.send(
            msg,
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            start_tls=self.starttls,
        )

    async def send_template(self, to: str, template: str, data: dict[str, Any]) -> None:
        # Renders via ``str.format`` to keep this adapter dependency-free —
        # apps that need Jinja / mjml swap in their own MailerContract.
        await self.send(to=to, subject=template, body=template.format(**data))

    async def verify_address(self, address: str) -> bool:
        return "@" in address


def plugin(settings: Any) -> None:
    from causeway import register

    host = getattr(settings, "smtp_host", None)
    if not host:
        return
    register(
        SmtpMailer(
            host=str(host),
            port=int(getattr(settings, "smtp_port", 587)),
            username=getattr(settings, "smtp_user", None),
            password=getattr(settings, "smtp_password", None),
            sender=str(getattr(settings, "smtp_sender", "noreply@localhost")),
        ),
    )


__all__ = ["SmtpMailer", "plugin"]
