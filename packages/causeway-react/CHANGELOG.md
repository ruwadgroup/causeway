# Changelog · `causeway-react`

All notable changes to the `causeway-react` npm package will be documented in
this file. Managed automatically by
[release-please](https://github.com/googleapis/release-please) from
[Conventional Commits](https://www.conventionalcommits.org/).

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.6-alpha.2] - 2026-06-01

### Fixed

- Repack against `@causewayjs/client` 0.1.0-alpha.2.
- Revalidate `useQuery` on mount by default without exposing stale cached data; opt into the old behavior with `keepPreviousData: true`.

## [0.2.6-alpha.0](https://github.com/tamimbinhakim/causeway/compare/dyadpy-react-v0.2.5-alpha.0...causeway-react-v0.2.6-alpha.0) (2026-05-30)

### Features

- Publish the route-key React provider and hooks backed by `@causewayjs/client`.
- Expose `useOptionalCausewayClient()` for integrations that can reuse a provider client when present.

## [0.2.5-alpha.0](https://github.com/tamimbinhakim/causeway/compare/dyadpy-react-v0.2.2-alpha.0...dyadpy-react-v0.2.5-alpha.0) (2026-05-25)

### ⚠ BREAKING CHANGES

- `createReactClient(api, routes)` now expects generated `routeMeta` instead
  of the old full `_routes` descriptor array.

### Features

- bind React hooks from lightweight route metadata so apps do not need to
  import full route descriptors just to construct the hook tree.
- require `causeway-ts>=0.1.5-alpha.0` for the lazy generated-client runtime.

## [0.2.2-alpha.0](https://github.com/tamimbinhakim/causeway/compare/dyadpy-react-v0.2.1-alpha.0...dyadpy-react-v0.2.2-alpha.0) (2026-05-21)


### Bug Fixes

* infer optional react route args ([7c689fe](https://github.com/tamimbinhakim/causeway/commit/7c689fe753d7957dd07f7603c3ffada6740930bc))

## [0.2.1-alpha.0](https://github.com/tamimbinhakim/causeway/compare/dyadpy-react-v0.2.0-alpha.0...dyadpy-react-v0.2.1-alpha.0) (2026-05-21)


### Bug Fixes

* preserve optional react route args ([a35e546](https://github.com/tamimbinhakim/causeway/commit/a35e5462eed948bed46dba54606c1e565420fe23))

## [0.2.0-alpha.0](https://github.com/tamimbinhakim/causeway/compare/dyadpy-react-v0.1.2-alpha.0...dyadpy-react-v0.2.0-alpha.0) (2026-05-21)


### ⚠ BREAKING CHANGES

* **causeway-react:** previous flat shape removed. Bumps to 0.1.2-alpha.5.

### Features

* **causeway-react:** tRPC-style nested client (createNestedClient) ([9cb4501](https://github.com/tamimbinhakim/causeway/commit/9cb45011f0c57aaa26c92230c81e5e0b456f0d76))
* standardize nested typed clients ([93ad484](https://github.com/tamimbinhakim/causeway/commit/93ad484eb0785e0af07790afb7f939114646cb07))


### Bug Fixes

* allow optional react query args ([c17cffb](https://github.com/tamimbinhakim/causeway/commit/c17cffb17b63270152f5acea4fb0f305a118f6c1))
* improve react client ssr typing ([631cc83](https://github.com/tamimbinhakim/causeway/commit/631cc83d06bb4245cc6758c0002327a7c32a4dcd))
* improve react query integration typing ([7d208f7](https://github.com/tamimbinhakim/causeway/commit/7d208f7ce05b0ea38bd532ba4b8d55b709ea629c))


### Refactor

* **causeway-react:** single nested-client surface, drop flat shape ([efb6e05](https://github.com/tamimbinhakim/causeway/commit/efb6e05415a980f7b1aae0070990d2f14eefe735))

## [0.1.2-alpha.0](https://github.com/tamimbinhakim/causeway/compare/dyadpy-react-v0.1.1-alpha.0...dyadpy-react-v0.1.2-alpha.0) (2026-05-20)


### Features

* **react:** add createReactClient ([a390a4e](https://github.com/tamimbinhakim/causeway/commit/a390a4e397fa62a3d738e6c2a957534d666ac5c6))

## [0.1.1-alpha.0](https://github.com/tamimbinhakim/causeway/compare/dyadpy-react-v0.1.0-alpha.0...dyadpy-react-v0.1.1-alpha.0) (2026-05-20)


### Features

* **react:** document SSR prefetch support ([ffc6c3d](https://github.com/tamimbinhakim/causeway/commit/ffc6c3d2c6650f5d034fe06073a9b6f439740545))

## [Unreleased]

### Added

- Initial scaffold: `createDyadpyHooks(api)` factory returning
  `useQuery`, `useMutation`, and `useSubscription` hooks for
  Dyadpy-generated clients. Built on TanStack Query v5; the hook types
  are inferred from the generated `ApiRoutes` interface. `Result<T, E>`
  envelopes from Python `@raises(...)` decorators are unwrapped
  automatically, so `error` arrives at the call site as the typed
  discriminated union.
