# Writing a plugin

A Causeway plugin is one Python package that implements one or more contracts from `causeway.contracts` and exposes a `plugin(settings)` entry point.

## Scaffold one

```bash
causeway plugin new causeway-contrib-resend
```

This creates:

```
causeway-contrib-resend/
├── pyproject.toml
├── src/causeway_contrib_resend/
│   ├── __init__.py
│   └── adapter.py
└── tests/
    └── test_smoke.py
```

Pre-wired entry point in `pyproject.toml`, a smoke test that mounts a `TestApp` with the adapter installed, and a stub adapter class to fill in.

## Implement the contract

```python
# src/causeway_contrib_resend/adapter.py
from typing import Any, ClassVar
from resend import Resend


class ResendMailer:
    contract_version: ClassVar[str] = "v1.0"

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client: Resend | None = None

    async def startup(self, settings: Any) -> None:
        self._client = Resend(self._api_key)

    async def shutdown(self) -> None:
        # Resend is HTTP-only — nothing to close.
        pass

    async def ready(self) -> bool:
        return self._client is not None

    # Mailer contract
    async def send(self, to: str, subject: str, body: str) -> None:
        assert self._client is not None
        await self._client.send(to=to, subject=subject, html=body)

    async def send_template(self, to: str, template: str, data: dict[str, Any]) -> None:
        ...

    async def verify_address(self, address: str) -> bool:
        return "@" in address
```

> **Good to know.** Causeway uses `typing.Protocol`s for contracts — you don't have to inherit from anything. Implement the methods, declare `contract_version`, and you're conformant.

## Wire the entry point

```python
# src/causeway_contrib_resend/__init__.py
from causeway import register
from .adapter import ResendMailer


def plugin(settings):
    register(ResendMailer(api_key=settings.resend_api_key.get_secret_value()))
```

```toml
# pyproject.toml
[project]
name = "causeway-contrib-resend"
dependencies = ["causeway>=0.1,<2.0", "resend>=1.0"]

[project.entry-points."causeway.plugins"]
resend = "causeway_contrib_resend:plugin"
```

Once installed (`uv add causeway-contrib-resend`), Causeway calls `plugin(settings)` at startup; `register()` adds the adapter; lifecycle takes over.

## Contributing settings fields

If your plugin needs typed config fields the app didn't declare, contribute them via `settings_fragment()`:

```python
from pydantic import SecretStr

class ResendMailer:
    contract_version = "v1.0"

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key

    def settings_fragment(self) -> dict:
        return {"resend_api_key": SecretStr("")}   # default; user sets via env

    async def startup(self, settings) -> None:
        key = self._api_key or settings.resend_api_key.get_secret_value()
        self._client = Resend(key)
```

The framework merges fragments into the app's `Settings` instance before `startup` fires. Users set the field via env vars / `.env` like any other setting (`RESEND_API_KEY=re_...`).

## Declaring dependencies on other contracts

A plugin that needs another contract to be present at startup lists it via `requires`:

```python
class StripeBilling:
    contract_version = "v1.0"
    requires = ["DBSession", "KV"]
```

Causeway refuses to boot if `requires` aren't met. Use this when your adapter is meaningless without another (e.g. a billing plugin that persists to your DB).

## Testing your plugin

```python
# tests/test_smoke.py
import pytest
from causeway.testing import TestApp
from causeway_contrib_resend import ResendMailer
from causeway import register


@pytest.fixture
async def app():
    register(ResendMailer(api_key="test-key"))
    return TestApp.from_routes("tests/fixtures/routes")


async def test_smoke(app):
    r = await app.get("/healthz")
    assert r.status_code == 200
```

For richer testing, expose a `*Fake` variant in the same package:

```python
class FakeResendMailer(ResendMailer):
    def __init__(self): ...
    async def startup(self, settings): self._client = None
    async def send(self, to, subject, body):
        self.sent.append((to, subject, body))
```

## Packaging checklist

Before publishing:

- [ ] `pyproject.toml` declares `causeway>=0.1,<2.0` as a dependency.
- [ ] Entry point under `causeway.plugins` is wired.
- [ ] Adapter sets `contract_version = "v1.0"`.
- [ ] `startup`, `shutdown`, `ready` are all defined (even if no-op).
- [ ] Smoke test mounts a `TestApp` with the adapter installed.
- [ ] README explains: what contract(s) it implements, what env vars it reads, what backend it talks to.

## Naming

Bundled official adapters live under `causeway.contrib` and install through
extras. Third-party packages should use `causeway-contrib-<thing>` to make the
boundary clear.

## Submitting an official adapter

The on-ramp for bundled `causeway.contrib` adapters lives in
[`internals/plugin-authoring.md`](../internals/plugin-authoring.md).

## Next

- [Plugins overview](./plugins.md)
- [Reference — contracts](../reference/classes/contracts.md)
- [Reference — `register`](../reference/functions/register.md)
