"""S3-compatible storage adapter (AWS S3, Cloudflare R2, MinIO).

Implements :class:`causeway.contracts.Storage` against any S3-compatible object
store. Works with the standard ``AWS_*`` env vars or explicit credentials.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, ClassVar, cast

import aioboto3  # type: ignore[import-untyped]


class S3Storage:
    contract_version: ClassVar[str] = "v1.0"

    def __init__(
        self,
        *,
        bucket: str,
        region: str | None = None,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        self.bucket = bucket
        self.region = region
        self.endpoint_url = endpoint_url
        self.access_key = access_key
        self.secret_key = secret_key
        self._session: aioboto3.Session | None = None

    async def startup(self, settings: Any) -> None:
        self._session = aioboto3.Session(
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        )

    async def shutdown(self) -> None:
        self._session = None

    async def ready(self) -> bool:
        return self._session is not None

    def _client(self) -> Any:
        if self._session is None:
            msg = "S3Storage used before startup()"
            raise RuntimeError(msg)
        return self._session.client("s3", endpoint_url=self.endpoint_url)

    async def put(self, key: str, body: bytes, *, content_type: str | None = None) -> None:
        async with self._client() as s3:
            kwargs: dict[str, Any] = {"Bucket": self.bucket, "Key": key, "Body": body}
            if content_type is not None:
                kwargs["ContentType"] = content_type
            await s3.put_object(**kwargs)

    async def get(self, key: str) -> bytes:
        async with self._client() as s3:
            resp = await s3.get_object(Bucket=self.bucket, Key=key)
            return cast(bytes, await resp["Body"].read())

    async def delete(self, key: str) -> None:
        async with self._client() as s3:
            await s3.delete_object(Bucket=self.bucket, Key=key)

    async def signed_url(self, key: str, *, expires: int = 3600) -> str:
        async with self._client() as s3:
            return cast(
                str,
                await s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": key},
                    ExpiresIn=expires,
                ),
            )

    async def list(self, prefix: str = "") -> AsyncIterator[str]:
        async with self._client() as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    yield str(obj["Key"])


def plugin(settings: Any) -> None:
    from causeway import register

    bucket = getattr(settings, "s3_bucket", None)
    if not bucket:
        # Auto-load gets ``None`` settings before the app's Settings load.
        # Skip silently; the explicit ``register(...)`` path stays available.
        return
    register(
        S3Storage(
            bucket=str(bucket),
            region=getattr(settings, "s3_region", None),
            endpoint_url=getattr(settings, "s3_endpoint_url", None),
        ),
    )


__all__ = ["S3Storage", "plugin"]
