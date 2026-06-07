# Releases

How a commit becomes a PyPI version. Short version: you don't bump anything by hand — release-please does it from your Conventional Commits.

## The pipeline

```
                                  ┌─────────────────────────┐
  feat(routing): ...               │                         │
  fix(plugins): ...     ─────────► │  release-please bot     │
  chore(deps): bump …              │  maintains a release    │
                                   │  PR per package         │
                                   └────────────┬────────────┘
                                                │ (you merge it when ready)
                                                ▼
                          ┌──────────────────────────────────────┐
                          │  bumps version, writes CHANGELOG,    │
                          │  tags the commit, opens PR closed    │
                          └────────────┬─────────────────────────┘
                                       │
                                       ▼
                          ┌──────────────────────────────────────┐
                          │  release.yml workflow on the tag:    │
                          │  builds wheel + sdist, publishes     │
                          │  to PyPI via trusted publishing      │
                          └──────────────────────────────────────┘
```

The whole thing is automated. The only manual step is **merging the release PR** when you decide it's time to cut.

## Conventional Commits

The commit message drives the bump:

| Prefix                       | Bump  | Example                                               |
| ---------------------------- | ----- | ----------------------------------------------------- |
| `fix:`                       | patch | `fix(routing): reject invalid route filename clearly` |
| `feat:`                      | minor | `feat(tasks): cron decorator emits to active adapter` |
| `feat!:` / `BREAKING CHANGE` | major | `feat(client)!: make route keys the only public API`  |
| `chore:`, `docs:`, `style:`  | none  | `docs: clarify route-key client examples`             |
| `refactor:`, `test:`, `ci:`  | none  | `refactor(_paths): simplify leaf tokenizer`           |

Common scopes: `routing`, `config`, `di`, `tasks`, `plugins`, `cli`, `observability`, `errors`, `testing`, `docs`, `ci`, `deps`.

The commit-msg hook (from `pnpm install`) rejects messages that don't match. If you need to fix a rejected message, `git commit --amend`.

## What release-please does

It watches `main` for commits since the last tag. As soon as one of them is a `feat:` or `fix:`, it opens (or updates) a **release PR** with:

- A `CHANGELOG.md` patch that groups the commits by section (Features / Bug Fixes / Performance / etc.).
- A bump to the version in `pyproject.toml`.
- A bump to the version constant in `causeway/__init__.py` (if applicable).

You **review the release PR like any other PR**. If something looks wrong — a `feat:` that should have been a `fix:`, a `BREAKING CHANGE:` you didn't realize you wrote — you fix the underlying commit (revert + recommit with the right prefix) and release-please will rebuild the PR.

When the PR looks right, you merge it. That triggers the publish workflow.

## Publish workflow

`.github/workflows/release.yml` (or whatever the file is called in the repo) is triggered on the tag created by the release PR. It:

1. Sets up uv + Python.
2. Runs the full test suite one more time. Belt and suspenders.
3. Builds the wheel and sdist with `uv build`.
4. Publishes to PyPI via [trusted publishing](https://docs.pypi.org/trusted-publishers/). No API tokens in repo secrets.
5. Creates a GitHub Release with the changelog excerpt.

If step 3 fails, **don't manually `twine upload`**. Fix the workflow. The audit trail matters.

## Pre-release versions

The current version is `0.1.0a0` — an alpha. Anything published from `main` before v0.1 ships will keep the `a<N>` suffix.

To bump the alpha (e.g. `a0 → a1`), include `BREAKING CHANGE:` in the commit footer or use a `feat!:` prefix. release-please understands prerelease semantics.

To cut the actual v0.1.0 release, manually edit the release PR's version field to `0.1.0`, drop the `a` suffix, then merge.

## Hotfixes on shipped versions

If `1.4.0` is in production and you need to ship `1.4.1` without picking up everything else on `main`:

1. Branch from the `v1.4.0` tag: `git checkout -b release/1.4.x v1.4.0`.
2. Cherry-pick the `fix:` commits you want.
3. Push the branch. release-please runs against it and opens a release PR for `1.4.1`.
4. Merge the PR. Publish workflow ships it.
5. **Forward-port** the same fixes to `main` if they aren't already there.

The hotfix branch is named `release/<major>.<minor>.x`. release-please knows that convention.

## Bundled adapters

Official adapters ship inside the single `causeway` PyPI package under
`causeway.contrib`. Their contract version (`v1.0`, etc.) is independent of
the package version and follows the framework's contract surface. Conventional
Commits still scope the bump, but release-please opens one release PR and the
publish workflow ships one PyPI package.

## What you do not do

- **Manually edit `CHANGELOG.md`.** release-please owns it. Your hand-edits will be overwritten.
- **Manually bump `pyproject.toml`'s version.** Same.
- **`twine upload` from a laptop.** Trusted publishing only.
- **Force-push to `main` after a tag.** The tag is immutable; rewriting history orphans it.
- **Skip the test suite to ship a "quick fix".** If CI is red, the release is wrong. Fix the underlying issue.

## When the release PR looks wrong

The two most common failure modes:

1. **A commit was scoped wrong.** A `fix:` for a real behavior change becomes a `feat:`, or vice versa. Revert the commit on main, recommit with the right prefix, push. release-please updates the PR.
2. **The changelog section is empty for a real change.** That means the commit was a `chore:` / `refactor:` / `test:` — those don't generate changelog entries by design. If the change is user-visible, the commit message was wrong; revert + recommit.

If you can't figure out what's going on, leave the PR open and ask. Releases don't ship on a clock.
