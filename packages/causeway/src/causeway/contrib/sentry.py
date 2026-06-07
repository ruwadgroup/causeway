"""Sentry integration. Initializes the SDK on startup, lets the SDK's
ASGI/Starlette integrations handle the rest.
"""

from __future__ import annotations

from typing import Any, ClassVar

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration


class SentryObserver:
    contract_version: ClassVar[str] = "v1.0"

    def __init__(
        self,
        *,
        dsn: str,
        environment: str = "dev",
        traces_sample_rate: float = 0.1,
    ) -> None:
        self.dsn = dsn
        self.environment = environment
        self.traces_sample_rate = traces_sample_rate

    async def startup(self, settings: Any) -> None:
        sentry_sdk.init(
            dsn=self.dsn,
            environment=self.environment,
            traces_sample_rate=self.traces_sample_rate,
            integrations=[StarletteIntegration(), AsyncioIntegration()],
        )

    async def shutdown(self) -> None:
        client = sentry_sdk.get_client()
        if client is not None:
            client.close()

    async def ready(self) -> bool:
        return sentry_sdk.get_client() is not None


def plugin(settings: Any) -> None:
    from causeway import env, register

    dsn = getattr(settings, "sentry_dsn", None)
    if not dsn:
        return
    if hasattr(dsn, "get_secret_value"):
        dsn = dsn.get_secret_value()
    register(SentryObserver(dsn=str(dsn), environment=env()))


__all__ = ["SentryObserver", "plugin"]
