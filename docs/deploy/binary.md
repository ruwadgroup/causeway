# Binary export

`causeway build --binary` produces a single AOT-compiled executable containing your
routes, plugins, settings, and a stripped Causeway runtime. Useful when you
want to self-host a backend without a Python interpreter on the target
machine, ship a reduced supply-chain surface, or run from a `FROM scratch`
container.

The binary is built with [Nuitka](https://nuitka.net) — it compiles your
Python to C, then to machine code. Compared to PyInstaller/PyOxidizer:

- The binary contains compiled `.so`/`.pyd` artifacts, not `.pyc` files in
  a zip. Decompiling back to source is materially harder.
- No self-extract-to-`/tmp` step; cold start is ~5–10× faster.
- Static linking against the Python interpreter means one file, no DLLs.

## When to use this

| Use it when…                                                         | Don't use it when…                                                                                             |
| -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| You self-host on Linux servers / VMs / Docker.                       | You target Vercel / Cloudflare / Lambda — those want a Python or Node handler, not a binary.                   |
| You want a `FROM scratch` container image (~15 MB).                  | You're iterating on routes in dev — `causeway dev` is the right loop.                                          |
| You ship to customers who shouldn't read the source.                 | Your app loads route files at runtime via `importlib` (binary freeze is AOT — runtime discovery breaks).       |
| You want one artifact to sign / SBOM / promote between environments. | You use plugins that register through entry points _at runtime_ outside the standard `causeway.plugins` group. |

## Build flow

```bash
pip install 'causeway[binary]'              # adds nuitka as a build dep
causeway build --binary --target dist       # ~3–10 min compile
```

`causeway freeze` runs step 1 alone (the AOT mirror), skipping Nuitka —
useful for inspecting the generated tree or caching it between CI runs.

What runs under the hood:

1. **Freeze.** Walks `app/routes/`, mirrors it into `.causeway/build/` with
   name-mangling (so `$id.py` becomes a valid Python module), and emits
   three static modules: `_frozen_routes.py`, `_frozen_plugins.py`,
   `_frozen_entry.py`. Entry-point plugins are resolved against your
   installed packages and baked in.
2. **Compile.** Invokes Nuitka with `--standalone --onefile --lto=yes`,
   includes the user's `app` package plus every detected plugin, and
   excludes the dev surface (`causeway.cli`, `_scaffold`, `_freeze`,
   `_binary`, `watchfiles`, `rich`, `typer`).
3. **Manifest.** Writes SHA-256 hashes of the generated modules into
   `manifest.json` bundled with the binary. On startup, the binary
   re-hashes the loaded modules and refuses to start if they don't match.

Output:

```
dist/
└── myapp-0.1.0-linux-x86_64                # single executable
```

Add `--sign` for a [cosign](https://docs.sigstore.dev/cosign/overview/)
signature next to the binary, and `--sbom` for a CycloneDX SBOM via
[syft](https://github.com/anchore/syft):

```
dist/
├── myapp-0.1.0-linux-x86_64
├── myapp-0.1.0-linux-x86_64.sig
└── myapp-0.1.0-linux-x86_64.sbom.json
```

`cosign sign-blob` runs keyless via Fulcio by default (the standard CI
flow); set `COSIGN_PRIVATE_KEY` to sign with a long-lived key instead.

## Running the binary

```bash
./dist/myapp-0.1.0-linux-x86_64
# listens on 0.0.0.0:8000 by default

PORT=9000 HOST=127.0.0.1 ./dist/myapp-0.1.0-linux-x86_64
```

Settings come from the same `pydantic-settings` class your dev server uses
(`app.config.Settings`); environment variables and `.env` files work as
they did before. The binary embeds the class definition; only the
_values_ are read at runtime.

## Threat model

What the binary protects against:

- **Casual source inspection.** Your routes and business logic ship as
  compiled artifacts, not as readable `.py` files. A determined attacker
  can still reverse-engineer with effort — this is obfuscation through
  compilation, not encryption.
- **Plugin-injection attacks.** Entry-point discovery is disabled at
  runtime (`causeway.plugins.discover()` returns `[]` when
  `CAUSEWAY_BUILD_MODE=binary`). An attacker who installs a malicious
  `causeway-*` package alongside the binary won't get their plugin loaded.
- **Frozen-module tampering.** A `manifest.json` next to the binary holds
  SHA-256 hashes of the frozen modules. Startup re-hashes and exits with
  a clear error on mismatch. This catches a PYTHONPATH-shadowing attack
  where someone drops a fake `_frozen_plugins.py` to hijack the binary.

What the binary does **not** protect against:

- **A compromised build environment.** If the machine running
  `causeway build --binary` is owned, the resulting binary is owned. Build on
  hardened CI (GitHub Actions with OIDC, GCP Cloud Build, etc.).
- **The diagnostics endpoint.** It's force-disabled in binary mode, but
  if you re-enable it in custom code, you re-expose the surface.
- **Replay or downgrade attacks at the distribution layer.** Use cosign +
  a transparency log (Rekor) for that — the manifest hash check alone
  is defense-in-depth, not a primary control.

## Verifying a signed binary

```bash
cosign verify-blob \
  --certificate-identity=https://github.com/you/your-repo/.github/workflows/release.yml@refs/tags/v0.1.0 \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com \
  --signature dist/myapp-0.1.0-linux-x86_64.sig \
  dist/myapp-0.1.0-linux-x86_64
```

Or with a long-lived key:

```bash
cosign verify-blob \
  --key cosign.pub \
  --signature dist/myapp-0.1.0-linux-x86_64.sig \
  dist/myapp-0.1.0-linux-x86_64
```

## Containerizing the binary

The `causeway[docker]` adapter emits a `FROM scratch` Dockerfile in
binary mode:

```python
from causeway.contrib.docker import DockerDeploy

DockerDeploy().package(
    target_dir="dist",
    binary=True,
    binary_name="myapp-0.1.0-linux-x86_64",
)
```

Resulting `dist/Dockerfile`:

```dockerfile
FROM scratch
COPY myapp-0.1.0-linux-x86_64 /app
EXPOSE 8000
ENTRYPOINT ["/app"]
```

Resulting image: ~15 MB, no shell, no Python, no package manager. The
distroless attack surface gets you ahead of the typical
`FROM python:3.13-slim` image (~150 MB with a writable filesystem and
`apt`/`pip` available).

## Known limitations

- **Build is slow.** 3–10 minutes for a real app. Cache `.causeway/build/`
  between CI runs to skip the freeze step when routes haven't changed.
- **First Nuitka run downloads the C compiler bootstrap** (gcc on Linux,
  Xcode CLT on macOS). Either pre-install in your build image or pass
  `--assume-yes-for-downloads` (already in the default command).
- **Cross-compilation isn't supported.** Build on the same OS/arch you
  ship to. Use a matrix in CI.
- **Plugins that do runtime importlib magic** (rare, but
  `causeway[growthbook]` does some) may need explicit
  `--include-package` hints. Pass them via the `extra_packages` argument
  to `build_binary()` or open an issue with the plugin.
