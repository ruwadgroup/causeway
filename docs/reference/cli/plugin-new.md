# `causeway plugin new`

Scaffold a new Causeway plugin package.

```bash
causeway plugin new causeway-contrib-resend
```

## Synopsis

```
causeway plugin new <name> [--target <dir>]
```

## Arguments

| Argument          | Default     | Description                                           |
| ----------------- | ----------- | ----------------------------------------------------- |
| `<name>`          | —           | Plugin package name (e.g. `causeway-contrib-resend`). |
| `--target` / `-t` | current dir | Parent directory.                                     |

## What it creates

```
causeway-contrib-resend/
├── pyproject.toml             # with the entry-point wiring pre-filled
├── README.md
├── src/causeway_contrib_resend/
│   ├── __init__.py            # plugin(settings) callable
│   └── adapter.py             # stub adapter class
└── tests/
    └── test_smoke.py          # TestApp-based smoke test
```

## Naming convention

- Bundled official adapters live under `causeway.contrib` and install through extras.
- Third-party packages should use `causeway-contrib-<thing>`.

## See also

- [Writing a plugin](../../app/plugin-authoring.md)
- [Plugins overview](../../app/plugins.md)
