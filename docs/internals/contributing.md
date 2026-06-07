# Contributing (deep)

The top-level [CONTRIBUTING.md](../../CONTRIBUTING.md) covers the on-ramp — clone, install, run tests, push. This page covers the conventions you'll trip over once you're past the first PR.

## Coding conventions

### Comments

The default is **no comment**. The bar to add one is:

- It documents a **hidden constraint** (a thing about the runtime, the protocol, or a library that's not visible from the code).
- It documents a **subtle invariant** (something a future refactor could break without realizing).
- It documents a **workaround for a specific bug** (with a link to the issue or PR).
- It documents **behavior that would surprise a reader** (e.g. "this `try` swallows on purpose because…").

Comments we don't want:

- Restating what the next line does. `# import dependencies`, `# return the user`, `# loop over plugins`.
- Section dividers. `# --- helpers ---` is just visual noise; ruff and the file structure already tell you where you are.
- Narrative explaining the design or "why we chose this." That goes in the PR description, the docs, or — if it's truly load-bearing — a module docstring at the top.
- References to the current task or fix. `# added for the welcome flow`, `# used by /signup` — those rot the moment the calling code changes.

When in doubt: delete it. If it was important, a reader will notice the thing it pointed at and ask, and then we can write a _better_ comment.

### Docstrings

One-line module / function docstrings stating the contract (the WHY or the invariant) are fine. Multi-paragraph WHAT docstrings that just restate the signature are not — the signature already says it.

```python
# good
def url_for(rel_path: PurePosixPath) -> str:
    """Translate a route file's relative path into a URL pattern."""

# bad
def url_for(rel_path: PurePosixPath) -> str:
    """
    Convert a file path to a URL.

    Args:
        rel_path: The path relative to the routes root.

    Returns:
        A string URL pattern.
    """
```

If you want examples, doctests are great. They double as tests.

### Error messages

Error messages are user interface. Two rules:

1. **State the failure, then say what to do next.** `"plugin X requires Y; no adapter for Y is registered"` is good. `"required dependency missing"` is bad.
2. **Quote user input back.** `f"route file must end in .py: {rel_path}"` is good. `"invalid file"` is bad.

### Backwards compatibility

Pre-1.0: break things freely. Just update the docs and add a migration note to `CHANGELOG.md` (release-please takes the rest).

Post-1.0: see [`docs/stability/semver.md`](../stability/semver.md). Short version — `feat:` is minor, `fix:` is patch, `feat!:` / `BREAKING CHANGE:` is major and goes through one full minor of `DeprecationWarning`.

### What not to add "just in case"

- Don't add error handling, fallbacks, or validation for scenarios that can't happen. Trust internal code. Validate only at system boundaries (user input, plugin discovery, HTTP/SSE).
- Don't add feature flags or backwards-compat shims when you can just change the code.
- Don't add abstractions for a hypothetical second implementation. Three similar lines are better than a premature interface.
- Don't add half-finished implementations behind `if False:` or `TODO:` blocks. If the feature isn't done, the branch isn't ready.

## Public-API rules

A symbol is **public** if it's re-exported from `causeway/__init__.py`. Everything else is internal and can break across patches.

When you add a public symbol:

1. Implement it in its module (e.g. `causeway/middleware.py`).
2. Re-export it from `causeway/__init__.py`.
3. Add it to that module's `__all__`.
4. Document it in [`docs/reference/`](../reference/index.md).
5. Write at least one test.

When you remove a public symbol (post-1.0):

1. Emit a `DeprecationWarning` for one full minor.
2. Update the changelog entry to flag the deprecation.
3. Remove in the next major.

## When to add a comment vs. delete one — flowchart

```
Is the comment explaining WHAT the code does?            → delete it
Is the comment restating the signature?                  → delete it
Is it a "added for X" reference to a current task?       → delete it
Is it a "---- section divider ----"?                     → delete it
Is it documenting a hidden constraint or subtle bug?     → keep, tighten if needed
Is it documenting a security-relevant decision?          → keep, make it impossible to miss
Is it a "TODO: implement X" without a tracked issue?     → delete or open the issue
```

## Built-in adapters

The official adapter set lives inside `packages/causeway/src/causeway/contrib/`.
Adapters with third-party dependencies are installed through extras such as
`causeway[s3]` and `causeway[dramatiq]`.

```
packages/causeway/
├── src/causeway/contrib/
│   ├── s3.py
│   ├── sqlmodel.py
│   └── dramatiq/
└── tests/contrib/
```

Conventions:

- Extras use the shortest clear backend name (`s3`, `redis`, `sqlmodel`, `dramatiq`).
- Modules live under `causeway.contrib.<extra>`.
- Adapter class names remain explicit (e.g. `DramatiqAdapter`, `S3Storage`, `JwtAuth`).
- Bundled adapters may expose a `plugin(settings)` helper, but apps usually register them explicitly from `plugins.py`.
- If the package needs settings fields the app didn't declare, expose a `settings_fragment()` method on the adapter that returns the field dict. The framework's `merge_settings_fragments` pass picks it up.
- Declare `contract_version: ClassVar[str] = "v1.0"` on the adapter class. The registry warns on mismatch.

Full walkthrough: [`plugin-authoring.md`](./plugin-authoring.md).

## When you don't know whether something is "official"

If the change is in `packages/causeway/src/causeway/`, it's the core framework
or a bundled adapter — held to the strict surface rules above.

If the change is in `examples/`, it's pedagogical — the only rule is "it actually runs."

If the change is in `docs/`, the only rule is "it matches the code." If it doesn't, the code is right and the docs are wrong; update the docs.

## How to ask a question

If you can ask the question by reading a file, please do. The codebase is small.

If you can ask the question by running a test (`uv run pytest -k <thing>`), please do.

If you've done both and still want a second opinion, open a Discussion. "How do I…" goes in Discussions, "I think this is broken" goes in Issues. The line is fuzzier than it sounds — when in doubt, pick Discussions; we can convert if it turns out to be a bug.
