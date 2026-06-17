# CLI

The `causeway` command. One entry point for project shape, dev loop, codegen, IR and App Graph introspection, and deployment.

```
$ causeway --help
causeway — a lean backend framework for type-safe Python APIs.

Commands:
  new <name>                 Scaffold a new app.
  dev                        Run the dev server + smart route hot-swap.
  build                      Emit the IR, the TS client, and a wheel.
  codegen                    Emit only the generated TS client.
  ir                         Emit the route IR as JSON.
  inspect                    Inspect the App Graph.
  freeze                     Emit the AOT build tree.
  openapi                    Emit OpenAPI 3.1 JSON.
  plugins                    List registered plugin adapters.
  plugin new <name>          Scaffold a new plugin package.
  diff <a> <b>               Compare two IR snapshots.
  deploy <target>            Invoke the relevant deploy adapter.
  version                    Print the installed version.
```

## Per command

| Command                      | Page                            |
| ---------------------------- | ------------------------------- |
| `causeway new <name>`        | [`new`](./new.md)               |
| `causeway dev`               | [`dev`](./dev.md)               |
| `causeway build`             | [`build`](./build.md)           |
| `causeway codegen`           | [`codegen`](./codegen.md)       |
| `causeway ir`                | [`ir`](./ir.md)                 |
| `causeway inspect`           | [`inspect`](./inspect.md)       |
| `causeway freeze`            | [`freeze`](./freeze.md)         |
| `causeway openapi`           | [`openapi`](./openapi.md)       |
| `causeway plugins`           | [`plugins`](./plugins.md)       |
| `causeway plugin new <name>` | [`plugin new`](./plugin-new.md) |
| `causeway diff <a> <b>`      | [`diff`](./diff.md)             |
| `causeway deploy <target>`   | [`deploy`](./deploy.md)         |
| `causeway version`           | [`version`](./version.md)       |
