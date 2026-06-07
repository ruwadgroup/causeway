# `causeway deploy`

Invoke the relevant `DeployTarget` plugin.

```bash
causeway deploy docker
causeway deploy fly
causeway deploy modal
```

## Synopsis

```
causeway deploy <target> [--output <dir>]
```

## Arguments

| Argument          | Default | Description                                                        |
| ----------------- | ------- | ------------------------------------------------------------------ |
| `<target>`        | —       | Adapter name (case-insensitive). Looks up `<Target>Deploy` plugin. |
| `--output` / `-o` | `dist/` | Directory the adapter writes its manifest into.                    |

## How it dispatches

The CLI scans registered plugins for one whose class name matches `<target>Deploy` (case-insensitive). For example:

- `causeway deploy docker` → looks for a `DockerDeploy` adapter.
- `causeway deploy fly` → looks for a `FlyDeploy` adapter.
- `causeway deploy modal` → looks for a `ModalDeploy` adapter.

If no adapter matches, the command fails with:

```
no DeployTarget registered for 'docker'. Install `causeway[docker]` and register it in `plugins.py`.
```

## Adapter contract

```python
class DeployTarget(Plugin, Protocol):
    def manifest(self) -> dict[str, Any]: ...
    def package(self) -> bytes: ...
    async def push(self, target: str) -> str: ...
```

## See also

- [Deploying](../../deploy/index.md)
- [`DeployTarget` contract](../classes/contracts.md#deploytarget)
