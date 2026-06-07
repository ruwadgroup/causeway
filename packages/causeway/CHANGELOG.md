# Changelog · `causeway`

All notable changes to the `causeway` Python package will be documented in this
file. Managed automatically by [release-please](https://github.com/googleapis/release-please)
from [Conventional Commits](https://www.conventionalcommits.org/).

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.3](https://github.com/ruwadgroup/causeway/compare/causeway-v0.6.2...causeway-v0.6.3) (2026-05-31)


### Bug Fixes

* **app:** start plugins before the app startup hook in lifespan ([cd96b50](https://github.com/ruwadgroup/causeway/commit/cd96b5063116bce3bf03762b041c09810b4690d1))

## [0.6.2](https://github.com/ruwadgroup/causeway/compare/causeway-v0.6.1...causeway-v0.6.2) (2026-05-29)


### Features

* add route-key client runtime ([ad5ce1b](https://github.com/ruwadgroup/causeway/commit/ad5ce1bfecee98fc441c7d8d013fbd865e8937ad))

## [0.6.1](https://github.com/ruwadgroup/causeway/compare/causeway-v0.6.0...causeway-v0.6.1) (2026-05-27)


### Bug Fixes

* **traceback:** keep error panel prefix-safe ([042d6bd](https://github.com/ruwadgroup/causeway/commit/042d6bd6c16c7ab09e6d014e4a34691f82adff63))

## [0.6.0](https://github.com/ruwadgroup/causeway/compare/causeway-v0.5.0...causeway-v0.6.0) (2026-05-27)


### ⚠ BREAKING CHANGES

* **npm:** scope JS packages under @causewayjs

### Features

* **errors:** add HTTP error formatter hook ([fb8e1a1](https://github.com/ruwadgroup/causeway/commit/fb8e1a1d58485b65e9222e321b34509482a4daf8))
* **npm:** scope JS packages under [@causewayjs](https://github.com/causewayjs) ([7dfa11e](https://github.com/ruwadgroup/causeway/commit/7dfa11e6051dbc398727a600a3cf87f0524c8ae5))

## [0.5.0](https://github.com/ruwadgroup/causeway/compare/causeway-v0.4.1...causeway-v0.5.0) (2026-05-27)


### ⚠ BREAKING CHANGES

* bring TS + Solid + Svelte + React packages under causeway brand
* absorb dyadpy into causeway as causeway._runtime

### Features

* absorb dyadpy into causeway as causeway._runtime ([f21fef1](https://github.com/ruwadgroup/causeway/commit/f21fef104ac52b214f74e0fa47b46b2d5d02e845))
* bring TS + Solid + Svelte + React packages under causeway brand ([502099f](https://github.com/ruwadgroup/causeway/commit/502099ffb8c92a72d24d4eeadf9ad59b424d3593))
* **traceback:** rich error panels and shield against double-logging ([eb14c51](https://github.com/ruwadgroup/causeway/commit/eb14c5130faadc203dde2a0783a42dc87c754271))


### Bug Fixes

* **observability:** detect structlog via sys.modules each request ([8dbfe13](https://github.com/ruwadgroup/causeway/commit/8dbfe13bc1e00d8168678a119f904b9579c1650c))


### Performance

* collapse class-middleware wraps + lazy-load structlog ([43cde88](https://github.com/ruwadgroup/causeway/commit/43cde88dc9a86c5d84b403c557503c0e62a907a4))

## [0.4.1](https://github.com/ruwadgroup/causeway/compare/causeway-v0.4.0...causeway-v0.4.1) (2026-05-25)

### ⚠ BREAKING CHANGES

- `causeway build` now writes the generated TypeScript client to
  `dist/client/` instead of `dist/client.ts`, matching Dyadpy's optimized
  generated-client layout.

### Features

- add smart dev hot reload that swaps changed route snapshots in-process
  without restarting uvicorn for ordinary route edits.
- keep the last good app serving when a reload fails, with rich route diff
  logging and short failure summaries.
- use compact uncaught exception tracebacks by default for cleaner terminal
  debugging.

### Bug Fixes

- keep typed error responses and webhook/pagination failures concise and
  copyable while preserving request ids and useful status fields.
- render undeclared `HttpError` values through Causeway's problem+json
  response path while Dyadpy still handles compact traceback logging for raw
  apps.

## [0.4.0](https://github.com/ruwadgroup/causeway/compare/causeway-v0.3.8...causeway-v0.4.0) (2026-05-23)

### ⚠ BREAKING CHANGES

- bracket route params are removed; use the `$name` convention for dynamic route files and folders.

### Features

- standardize file routing on `$name` dynamic segments for folders and dotted leaves.
- reject bracket route params at boot with a clear migration error.

## [0.3.8](https://github.com/ruwadgroup/causeway/compare/causeway-v0.3.7...causeway-v0.3.8) (2026-05-20)


### Bug Fixes

* **causeway:** register loaded route modules ([ca18a5d](https://github.com/ruwadgroup/causeway/commit/ca18a5d65984e546b7e623412c320eababb837f0))

## [0.3.7](https://github.com/ruwadgroup/causeway/compare/causeway-v0.3.6...causeway-v0.3.7) (2026-05-20)


### Bug Fixes

* keep routing provider binding type-safe ([ab4b94f](https://github.com/ruwadgroup/causeway/commit/ab4b94f925f5fddf5708c89086ce8f12af5c931b))

## [0.3.6](https://github.com/ruwadgroup/causeway/compare/causeway-v0.3.5...causeway-v0.3.6) (2026-05-20)


### Features

* own app plugin lifecycle ([fe48eff](https://github.com/ruwadgroup/causeway/commit/fe48eff65807d6b54019c8b1d9e0f10a3f638044))

## [0.3.5](https://github.com/ruwadgroup/causeway/compare/causeway-v0.3.4...causeway-v0.3.5) (2026-05-19)


### Bug Fixes

* **causeway:** resolve PEP 563 routes, fix param ordering, sort by specificity ([b07900f](https://github.com/ruwadgroup/causeway/commit/b07900f1621a32a440f8aca61111e68f05d226b2))

## [0.3.4](https://github.com/ruwadgroup/causeway/compare/causeway-v0.3.3...causeway-v0.3.4) (2026-05-19)


### Features

* **causeway:** [@use](https://github.com/use), [@dependency](https://github.com/dependency), and path-gated class middleware ([#20](https://github.com/ruwadgroup/causeway/issues/20)) ([a575e74](https://github.com/ruwadgroup/causeway/commit/a575e74089e92b9dee6535f8864b73b105344476))
* **causeway:** reshape events/webhooks around subscribers and a typed Event ([#21](https://github.com/ruwadgroup/causeway/issues/21)) ([646564f](https://github.com/ruwadgroup/causeway/commit/646564f66973aba67dd13fc4904ceb924b73c694))

## [0.3.3](https://github.com/ruwadgroup/causeway/compare/causeway-v0.3.2...causeway-v0.3.3) (2026-05-18)


### Features

* **causeway:** add file-based events and cooperative task cancellation ([8891920](https://github.com/ruwadgroup/causeway/commit/88919202b90776f6c2b111dc3dbf7a9bec39335b))

## [0.3.2](https://github.com/ruwadgroup/causeway/compare/causeway-v0.3.1...causeway-v0.3.2) (2026-05-18)


### Bug Fixes

* **causeway:** exercise class middleware in TestApp; correct codegen entry ([d54a7f4](https://github.com/ruwadgroup/causeway/commit/d54a7f48f3710729335f131202c8ca3110be0268))

## [0.3.1](https://github.com/ruwadgroup/causeway/compare/causeway-v0.3.0...causeway-v0.3.1) (2026-05-18)


### Features

* **causeway:** auto-coerce typed task args via annotations ([a3d9bb9](https://github.com/ruwadgroup/causeway/commit/a3d9bb9f960e5e5997cef990811f698fa4427952))

## [0.3.0](https://github.com/ruwadgroup/causeway/compare/causeway-v0.2.1...causeway-v0.3.0) (2026-05-17)


### ⚠ BREAKING CHANGES

* drops the 0.1.0a0 pre-release line. The first published versions on PyPI will be 0.1.0.
* the framework is now distributed as `causeway` (and `causeway-<role>-<impl>` for plugins). Every public surface moves:

### Features

* **causeway:** inline test scenarios with snapshot rewriting ([e897442](https://github.com/ruwadgroup/causeway/commit/e89744226ba6a2bcd72ea4cda1ef6416d795c044))
* **causeway:** v0.2 — pagination, batch, idempotency, permissions, webhooks, binary export ([45852fd](https://github.com/ruwadgroup/causeway/commit/45852fd2d6f80aa69d99770e4acdec0aeb67bf03))


### Chores

* prep first 0.1.0 release across all 13 packages ([11ef338](https://github.com/ruwadgroup/causeway/commit/11ef3382a6263cbe541455dd169a28cf162ebb3d))
* rename quay → causeway across the repo ([83f1213](https://github.com/ruwadgroup/causeway/commit/83f1213a2176e8338305f8b30f43379d6a614238))

## 0.1.0 (2026-05-16)


### ⚠ BREAKING CHANGES

* drops the 0.1.0a0 pre-release line. The first published versions on PyPI will be 0.1.0.
* the framework is now distributed as `causeway` (and `causeway-<role>-<impl>` for plugins). Every public surface moves:

### Chores

* prep first 0.1.0 release across all 13 packages ([11ef338](https://github.com/ruwadgroup/causeway/commit/11ef3382a6263cbe541455dd169a28cf162ebb3d))
* rename quay → causeway across the repo ([83f1213](https://github.com/ruwadgroup/causeway/commit/83f1213a2176e8338305f8b30f43379d6a614238))

## [Unreleased]

### Added

- Initial package scaffold: file-based router, typed config / DI,
  middleware + scope composition, background-task contract + reference
  adapter, plugin registry, `causeway` CLI.
