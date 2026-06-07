# File uploads

Routing file uploads through the ASGI process eats memory, ties up workers, and bottlenecks throughput on large files. The right pattern is presigned URLs: the server signs a one-shot upload URL, the client uploads direct to object storage, the server sees a finalize call with the object key.

## The flow

```
client ── POST /uploads/sign ─────> server  (returns signed URL + key)
client ── PUT signed-url ─────────> object storage
client ── POST /uploads/finalize ─> server  (records the key)
```

## Signing

```python
from causeway import post, register
from causeway.contracts import Storage
from causeway.contrib.s3 import S3Storage

register(S3Storage(bucket="user-uploads"))


@post
async def sign(filename: str, content_type: str, storage: Storage) -> SignedUpload:
    key = f"uploads/{uuid4()}/{filename}"
    url = await storage.presigned_put(
        key,
        expires=600,
        content_type=content_type,
        max_size_bytes=10 * 1024 * 1024,  # 10 MB cap
    )
    return SignedUpload(key=key, url=url)
```

`max_size_bytes` is a hint — S3 enforces it via the signed policy, `LocalStorage` ignores it. Set it conservatively.

## Downloading

`presigned_get` is the symmetric helper for one-shot download URLs:

```python
@get
async def download(key: str, storage: Storage) -> DownloadUrl:
    url = await storage.presigned_get(key, expires=600)
    return DownloadUrl(url=url)
```

`signed_url` from v0.1 still works — it's now an alias of `presigned_get`. New code should use the explicit names.

## Local development

`LocalStorage.presigned_put` returns a `file://` URL with a sentinel that's not actually uploadable. It's enough for tests and codegen; running an actual upload locally needs MinIO, LocalStack, or another S3-compatible adapter.
