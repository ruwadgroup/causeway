# The runtime substrate

Causeway ships in two layers:

- **The runtime substrate** — `causeway._runtime` — does the type-safe RPC
  work: walks Python handler signatures into an IR, decodes inbound
  bodies through `msgspec`, encodes responses, drives SSE streams, runs
  bidirectional WebSocket channels, and emits the typed TypeScript
  client off the same IR.
- **The convention layer** — everything else under `causeway/` — adds
  file-based routing, scope-based DI, plugin registry, background-task
  contract, observability, CLI, and the binary-build pipeline.

If you're building an application, you use the convention layer (the
top-level `causeway` package) and never need to think about the split.
This page is for the small set of cases where the split matters.

## When you'd reach into `causeway._runtime`

Three common reasons:

### 1. You're writing a library that needs the typed-RPC engine without the framework

You want `App` / `Context` / `Depends` / `stream` / `raises` /
`BidiChannel` and the IR/codegen, but you don't want file-based routing,
plugins, or the `create_app` lifecycle. Build directly on the runtime:

```python
from causeway._runtime import App, Context, Depends, stream

app = App()

@app.get("/users/{user_id}")
async def get_user(user_id: int, ctx: Context) -> dict[str, int]:
    return {"id": user_id}
```

`App` is the ASGI app. Mount it under uvicorn directly. No `create_app`,
no routes directory, no `plugins.py`. The TypeScript client still falls
out — `causeway codegen` works on any object that walks down to a
`causeway._runtime.App`.

### 2. You're writing your own opinionated framework on top

The substrate is stable and documented; nothing about it is
private-to-the-convention-layer. Build a framework with different
opinions (different routing convention, different DI shape, different
discovery mechanism) and re-use the IR + codegen. The convention layer
is one example of what's possible — not the only one.

The minimum your framework needs to do:

1. Create a `causeway._runtime.App` instance.
2. Register handlers on it via the verb decorators (`@app.get(path)`,
   `@app.post(path)`, …) or directly via `app.routes.append(Route(...))`.
3. Hand the resulting `App` to whatever ASGI server you're using.
4. (Optional) Run `causeway._runtime.ir.build_ir(app)` →
   `causeway._runtime.codegen.write(ir, out)` to emit the TypeScript
   client.

That's it. Everything else — scope graphs, plugin registries, lifecycle
phases — is your framework's call.

### 3. You're writing custom codegen for another language

The IR is the contract. `causeway._runtime.ir.AppIR` is a pure
data structure. Walk it however you want. The shipping renderers
(`causeway._runtime.codegen` for TypeScript and
`causeway._runtime.openapi` for OpenAPI 3.1) are both built on the same
public IR — your renderer joins the same line.

## The substrate's public surface

Everything you'd touch:

| Symbol                            | What                                                                     |
| --------------------------------- | ------------------------------------------------------------------------ |
| `App`                             | The ASGI app + route registry. `app.get(...)` / `post` / etc.            |
| `Context`                         | Per-request handle: status, headers, cookies, after-callbacks.           |
| `Depends`                         | DI marker for handler parameters.                                        |
| `after`                           | Register a callback to run after the response is sent.                   |
| `stream[T]`                       | Return annotation for SSE-streaming handlers.                            |
| `raises(*excs)`                   | Declare typed errors; flow to route metadata and client `RouteError<K>`. |
| `bidi`, `BidiChannel[S, R]`       | Bidirectional WebSocket channels.                                        |
| `Form`, `Bytes`, `SsePayload`     | Body markers + raw-bytes sentinel + SSE payload helper.                  |
| `causeway._runtime.params.*`      | `Body`, `Header`, `Path`, `Query`, `Cookie`, `File` markers.             |
| `causeway._runtime.ir.build_ir`   | Walk an `App` into an `AppIR`.                                           |
| `causeway._runtime.codegen.write` | Emit the TypeScript client folder.                                       |
| `causeway._runtime.diff.diff_ir`  | Diff two IR snapshots; flags breaking changes.                           |

All of these are re-exported at the top of the `causeway` package, so
the application-author path stays:

```python
from causeway import App, Context, Depends, get, post, stream, raises
```

Reach into `causeway._runtime` only when you need primitives the
convention layer doesn't surface (e.g. raw `Body` markers, IR
construction, custom codegen entry points).

## The substrate's stability promise

The runtime substrate follows the same semver as the rest of Causeway:

- `App.get` / `App.post` / `App.put` / `App.patch` / `App.delete` /
  `App.websocket` — stable signatures, won't break in minor releases.
- `Context` attributes that are documented — stable.
- `AppIR`, `RouteIR`, `ParamIR` JSON shape — versioned via
  [IR stability](../stability/ir-stability.md). Field additions are
  non-breaking; renames or removals bump the major.
- Codegen output shape — stable enough to bundle into your build, but
  the renderer can change format details (whitespace, comment banners,
  helper type names) within a minor release.

What's _not_ stable:

- `causeway._runtime.runtime.*` internals (`RouteRunner`, `HandlerPlan`,
  the resolver). These are implementation details. Don't import.
- `causeway._runtime._pydantic.*` / `causeway._runtime._idents.*` —
  underscore-prefixed because they're private helpers.

## Why the layering stays internal

Earlier in Causeway's life, the substrate lived behind its own package
boundary. That worked architecturally but added cost for users: two
install lines, two changelogs, two versions to keep in sync, two
namespaces in every traceback. The capability — typed RPC, IR, codegen,
streaming, bidi — was the actually-valuable thing, not the brand. So it
folded into Causeway as `causeway._runtime`.

The boundary survives as architecture: you can use the substrate
standalone (case 1 above), you can build a different framework on it
(case 2), and you can read it as one focused module (everything in
`causeway/_runtime/`) without scrolling through the convention layer.
Only the brand boundary went away.

## See also

- **[Boot pipeline](./boot-pipeline.md)** — what runs between
  `causeway dev` and your first request.
- **[IR flow](./ir-flow.md)** — how a Python signature becomes a
  TypeScript type.
- **[IR stability](../stability/ir-stability.md)** — semver for the IR
  schema itself.
- **[Internals: code map](../internals/code-map.md)** — a file-by-file
  tour, including the `_runtime/` subtree.
