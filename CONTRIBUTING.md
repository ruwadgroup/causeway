# Contributing to Causeway

First: thank you. Genuinely. Open source moves at the speed of the people who
show up, and you showing up means a lot.

This guide will get you from "I cloned the repo" to "my PR is merged" with as
little friction as possible. If something here is wrong, unclear, or just
annoying, open a PR fixing it — meta-contributions count.

## TL;DR

```bash
git clone https://github.com/ruwadgroup/causeway.git
cd causeway
pnpm install               # installs Node deps + sets up husky hooks
uv sync                    # installs Python deps into .venv
pnpm test                  # run the test suite
```

You're set up. Make a branch, make a change, write a Conventional Commit, push.

## What this repo is

A pnpm monorepo with one publishable Python package and a pile of supporting
docs/examples:

```
causeway/
├── packages/
│   └── causeway/             # Python framework (PyPI: causeway)
├── examples/             # Runnable apps you can poke
├── docs/                 # End-user documentation
└── .github/              # CI, issue templates, the works
```

## Prereqs

| Tool   | Version          | Why                                                                                     |
| ------ | ---------------- | --------------------------------------------------------------------------------------- |
| Node   | ≥ 22             | Runs the toolchain (pnpm, husky, commitlint, prettier).                                 |
| pnpm   | ≥ 10             | Workspace package manager. Don't use npm/yarn here.                                     |
| Python | ≥ 3.11           | Causeway leans on modern typing (`from __future__ import annotations`, `X \| Y`, etc.). |
| uv     | latest           | Python package manager. Way faster than pip.                                            |
| Git    | any sane version | Obvious.                                                                                |

> On macOS, `brew install node pnpm uv python@3.13` covers it.

## First-time setup

```bash
pnpm install        # Node deps + husky hooks via the `prepare` script
uv sync             # Creates .venv and installs Python deps
```

That's it. There is no third step.

To verify:

```bash
pnpm lint           # ruff + prettier
pnpm format         # ruff format (Python) + prettier (md/json/yaml)
pnpm typecheck      # mypy
pnpm test           # pytest
```

> Formatter split: **ruff** handles Python, **prettier** handles
> `*.md`/`*.json`/`*.yaml`. Each tool owns its filetypes.

If all four are green on a fresh clone, you're good. If they aren't, that's a
bug — open an issue.

## Day-to-day

### Branches

Branch off `main`. Use whatever naming you like, but a hint:

```
feat/file-router-route-groups
fix/middleware-order-on-nested-scope
docs/getting-started-typo
chore/bump-pydantic-settings
```

### Commits

We use [Conventional Commits](https://www.conventionalcommits.org/). The
`commit-msg` hook will reject anything that doesn't match. Examples:

```
feat(routing): support (group)/ route groups
fix(di): scope provider cleanup ordering
docs: clarify cron decorator semantics
chore(deps): bump pydantic-settings
```

Scopes are optional but appreciated. Common ones: `routing`, `config`, `di`,
`tasks`, `plugins`, `cli`, `docs`, `ci`, `deps`.

### Pre-commit

`pnpm install` wires up:

- **commit-msg** → commitlint validates your message
- **pre-commit** → lint-staged runs ruff on staged Python files and prettier
  on staged docs

If the hook fails, fix the issue and re-stage. Don't bypass with
`--no-verify` unless you have a really good reason.

## Working on the Python package

```bash
cd packages/causeway
uv run pytest                  # full test suite
uv run pytest -k routing       # one area
uv run ruff check .            # lint
uv run ruff format .           # format
uv run mypy src                # type-check
```

The package layout:

```
packages/causeway/
├── src/causeway/
│   ├── __init__.py     # public API re-exports
│   ├── routing/        # file-based router + middleware + scopes
│   ├── config.py       # pydantic-settings wrapper
│   ├── di.py           # scoped DI container
│   ├── tasks.py        # @task contract + Dramatiq reference adapter
│   ├── plugins.py      # entry-point registry + register()
│   ├── observability.py
│   ├── health.py
│   ├── errors.py
│   ├── testing.py
│   └── cli.py
└── tests/
```

When adding a new public symbol, re-export it from `causeway/__init__.py`.

## Working on examples

```bash
cd examples/minimal
uv sync
uv run causeway dev
```

Each example is self-contained. They are not part of the publish pipeline —
they exist to demo features and catch regressions in real-world setups.

## Tests

We don't enforce a coverage number, but we do enforce that:

- Every bug fix adds a regression test.
- Every new public API has at least one test.
- The routing, DI, and plugin-registry modules in particular should have
  generous tests — they are the load-bearing parts.

## Documentation

If you change behavior, update the relevant page in [`docs/`](./docs).
If you change a public API, update the docstring **and** the docs page.
If your change is interesting, write a paragraph about _why_ — future-you
will thank you.

## Releases

Releases are automated via [release-please](https://github.com/googleapis/release-please).

- Every merge to `main` updates a release PR.
- Merging that release PR cuts versions, generates the changelog, tags, and
  publishes `causeway` to PyPI.
- Versioning is driven by Conventional Commits: `feat:` → minor, `fix:` →
  patch, `feat!:` / `BREAKING CHANGE:` → major.

You don't manually bump versions. Don't manually edit `CHANGELOG.md` either —
release-please owns it.

## Filing issues

Use the issue templates. They exist to save you time, not to gatekeep.

If you've found a bug:

1. **A minimal reproduction beats everything.** A 20-line script that fails
   is worth more than a 500-word description.
2. Tell us the version (`causeway --version`) and Python version.
3. If it's a routing / IR issue, paste the directory tree and the offending
   handler.

## Asking questions

Discussions for "how do I…?" and design questions.
Issues for "I think this is broken."

## Code of Conduct

Be kind. Disagree with ideas, not people. Read the
[full Code of Conduct](./CODE_OF_CONDUCT.md).

## Thanks

Seriously. Thanks for reading this. Now go break something.
