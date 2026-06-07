"""GrowthBook adapter for :class:`causeway.contracts.FeatureFlags`."""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
from growthbook import GrowthBook


class GrowthBookFlags:
    contract_version: ClassVar[str] = "v1.0"

    def __init__(self, *, api_host: str, client_key: str) -> None:
        self.api_host = api_host
        self.client_key = client_key
        self._features: dict[str, Any] = {}

    async def startup(self, settings: Any) -> None:
        await self.refresh()

    async def shutdown(self) -> None:
        self._features.clear()

    async def ready(self) -> bool:
        return bool(self._features)

    async def refresh(self) -> None:
        url = f"{self.api_host.rstrip('/')}/api/features/{self.client_key}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            self._features = resp.json().get("features", {})

    def _gb(self, user: str | None) -> GrowthBook:
        return GrowthBook(
            features=self._features,
            attributes={"id": user} if user else {},
        )

    async def is_on(self, flag: str, user: str | None = None) -> bool:
        return bool(self._gb(user).is_on(flag))

    async def variant(self, flag: str, user: str | None = None) -> str | None:
        result = self._gb(user).eval_feature(flag)
        return None if result.value is None else str(result.value)


def plugin(settings: Any) -> None:
    from causeway import register

    host = getattr(settings, "growthbook_api_host", None)
    key = getattr(settings, "growthbook_client_key", None)
    if not host or not key:
        return
    register(GrowthBookFlags(api_host=str(host), client_key=str(key)))


__all__ = ["GrowthBookFlags", "plugin"]
