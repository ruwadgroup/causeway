# Changelog · `causeway-ts`

All notable changes to the `causeway-ts` npm package will be documented in
this file. Managed automatically by
[release-please](https://github.com/googleapis/release-please) from
[Conventional Commits](https://www.conventionalcommits.org/).

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.7-alpha.0](https://github.com/ruwadgroup/causeway/compare/dyadpy-ts-v0.1.6-alpha.0...causeway-ts-v0.1.7-alpha.0) (2026-05-30)

### Features

- Publish the route-key client transport used by `@causewayjs/client`.

## [0.1.6-alpha.0](https://github.com/ruwadgroup/causeway/compare/dyadpy-ts-v0.1.5-alpha.0...dyadpy-ts-v0.1.6-alpha.0) (2026-05-26)


### Performance

* **codegen:** dedupe loadRoute chunk imports + opaque-path passthrough ([#33](https://github.com/ruwadgroup/causeway/issues/33)) ([c5aa528](https://github.com/ruwadgroup/causeway/commit/c5aa5285aed43e6ece1223133a99c4da442ae67f))

## [0.1.5-alpha.0](https://github.com/ruwadgroup/causeway/compare/dyadpy-ts-v0.1.2-alpha.0...dyadpy-ts-v0.1.5-alpha.0) (2026-05-25)

### ⚠ BREAKING CHANGES

- remove the eager `createClient({ routes })` / `ClientConfig` public path.
  Generated clients now use `createLazyClient({ routeMeta, loadRoute })`.

### Features

- add `createLazyClient`, `RouteMeta`, and `LazyClientConfig` so generated
  clients can keep route metadata small and load full descriptors on first use.
- surface typed and HTTP failures as `DyadpyError` instances with short,
  copyable messages while preserving `kind`, `status`, and extra typed fields.
- support request-scoped SSR header forwarding with clearer Promise misuse
  errors.

## [0.1.2-alpha.0](https://github.com/ruwadgroup/causeway/compare/dyadpy-ts-v0.1.1-alpha.0...dyadpy-ts-v0.1.2-alpha.0) (2026-05-21)


### Features

* standardize nested typed clients ([93ad484](https://github.com/ruwadgroup/causeway/commit/93ad484eb0785e0af07790afb7f939114646cb07))

## [0.1.1-alpha.0](https://github.com/ruwadgroup/causeway/compare/dyadpy-ts-v0.1.0-alpha.0...dyadpy-ts-v0.1.1-alpha.0) (2026-05-20)


### Features

* **dyadpy:** support SSR client factories ([bab8eb6](https://github.com/ruwadgroup/causeway/commit/bab8eb63e1bc4d24fe12a7c490e741c1599f2e50))

## [Unreleased]

### Added

- Initial scaffold: `createClient` Proxy factory, `parseSSE` minimal
  Server-Sent Events parser, shared `RouteDescriptor` / `Result` types.

## [0.1.7-alpha.2] - 2026-06-01

### Fixed

- Omit `null` and `undefined` query parameter values in the route-key client.
- Support `cache: "no-store"` call options so hook-driven refreshes can clear stale cached data before the network response returns.
