# @causewayjs/client

Owned Causeway client runtime for route-key queries, mutations, refreshes, streaming, and hydration.

```bash
pnpm add @causewayjs/client
```

Generated clients wrap this package. Most apps import `createClient` from the generated directory so route keys and input/output types narrow correctly:

```ts
import { createClient } from "./client";

const client = createClient({ baseUrl: "/api" });

const customer = await client.query("GET /customers/$id", { id });
await client.mutate("POST /customers/$id/screen", { id });
```

The runtime owns the cache. It dedupes in-flight queries, accepts inline input objects safely, supports abort signals, throws `CausewayError`, dehydrates for server rendering, hydrates on the client, and runs backend-declared `refreshes` after successful mutations.

## Shape

```ts
await client.query("GET /customers/$id", { id });
await client.refresh("GET /customers/$id", { id });
await client.mutate("PATCH /customers/$id", { id, data });

for await (const event of client.stream("GET /customers/$id/events", { id })) {
  console.log(event);
}
```

The public name is the route key. There is no generated method tree and no separate resource-key convention.

Generated `types.d.ts` registers `RouteInput<K>`, `RouteData<K>`, and
`RouteError<K>` with `@causewayjs/client`. The React hooks and Next prefetch
helpers read that same registry.

## License

MIT
