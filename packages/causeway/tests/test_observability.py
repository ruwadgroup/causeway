"""Request-id middleware + structlog setup."""

from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from causeway._runtime import App
from causeway.observability import RequestIdMiddleware, configure_logging


async def _echo(req):
    rid = req.scope.get("state", {}).get("request_id")
    return JSONResponse({"request_id": rid})


def _build_app() -> Starlette:
    return Starlette(routes=[Route("/", _echo)])


async def test_request_id_generated_when_missing() -> None:
    app = RequestIdMiddleware(_build_app())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    rid = resp.json()["request_id"]
    assert rid
    assert len(rid) >= 16
    assert resp.headers["x-request-id"] == rid


async def test_request_id_echoed_from_client() -> None:
    app = RequestIdMiddleware(_build_app())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/", headers={"x-request-id": "trace-123"})
    assert resp.json()["request_id"] == "trace-123"
    assert resp.headers["x-request-id"] == "trace-123"


def test_configure_logging_json_mode_runs() -> None:
    # Smoke test only — verifies the call doesn't raise and structlog is
    # configured. Anything beyond that is the user's logger choice.
    configure_logging(level="INFO", json=True)


@pytest.mark.asyncio
async def test_request_id_propagates_through_causeway_app() -> None:
    inner = App()

    @inner.get("/x")
    async def x() -> dict[str, str | None]:
        return {"ok": "yes"}

    wrapped = RequestIdMiddleware(inner)
    transport = httpx.ASGITransport(app=wrapped)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/x")
    assert "x-request-id" in resp.headers
