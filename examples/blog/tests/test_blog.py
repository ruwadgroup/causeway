"""End-to-end tests for the blog example.

Exercises: public read paths, admin guard, full create→publish→comment
flow, and that the comment background task fired.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from app.app import app
from app.config import settings
from app.db import create_all, dispose, engine
from app.notifications import clear as clear_notifications
from app.notifications import history
from causeway.plugins import shutdown_all, startup_all


@pytest.fixture(autouse=True)
async def _lifespan() -> AsyncIterator[None]:
    """Approximate the ASGI lifespan: tables + plugin startup once per test."""
    await create_all()
    await startup_all(settings)
    clear_notifications()
    try:
        yield
    finally:
        await shutdown_all()
        await dispose()
        clear_notifications()
        # Re-init engine for next test (we disposed it).
        engine.pool.recreate()


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://t")


def _admin_headers() -> dict[str, str]:
    return {"authorization": f"Bearer {settings.admin_token.get_secret_value()}"}


async def test_root_reports_site_title() -> None:
    async with _client() as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["site"] == settings.site_title


async def test_public_listing_excludes_drafts() -> None:
    async with _client() as c:
        # Create one draft + one published.
        draft = await c.post(
            "/admin/posts",
            json={"title": "draft", "body": "...", "published": False},
            headers=_admin_headers(),
        )
        live = await c.post(
            "/admin/posts",
            json={"title": "live", "body": "...", "published": True},
            headers=_admin_headers(),
        )
        assert draft.json()["ok"] is True
        assert live.json()["ok"] is True

        listing = await c.get("/posts")
        titles = [row["title"] for row in listing.json()]
    assert "live" in titles
    assert "draft" not in titles


async def test_admin_routes_require_token() -> None:
    async with _client() as c:
        resp = await c.get("/admin/posts")
    # `@raises(Unauthorized)` routes the failure through Causeway's envelope:
    # HTTP 200, body says ok=false with a discriminated error kind.
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["kind"] == "Unauthorized"


async def test_comment_flow_fires_background_task() -> None:
    async with _client() as c:
        created = await c.post(
            "/admin/posts",
            json={"title": "hello", "body": "world", "published": True},
            headers=_admin_headers(),
        )
        post_id = created.json()["data"]["id"]

        commented = await c.post(
            f"/posts/{post_id}/comments",
            json={"author": "ada", "body": "first!"},
        )
        assert commented.json()["ok"] is True

    # The InMemoryAdapter spawns the task on the running loop; give it a
    # tick to flush before we read the notification history.
    await asyncio.sleep(0.05)
    kinds = [n.kind for n in history()]
    assert "new_comment" in kinds


async def test_patch_and_delete_admin_post() -> None:
    async with _client() as c:
        created = await c.post(
            "/admin/posts",
            json={"title": "x", "body": "y", "published": False},
            headers=_admin_headers(),
        )
        post_id = created.json()["data"]["id"]

        patched = await c.patch(
            f"/admin/posts/{post_id}",
            json={"published": True},
            headers=_admin_headers(),
        )
        assert patched.json()["data"]["published"] is True

        deleted = await c.delete(
            f"/admin/posts/{post_id}",
            headers=_admin_headers(),
        )
    assert deleted.json() == {"ok": True, "data": {"deleted": True}}
