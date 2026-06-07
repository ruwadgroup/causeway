# Client Runtime

Causeway emits a TypeScript client from the same route IR that powers runtime validation. The public identity is the route key:

```ts
const user = await client.query("GET /users/$id", { id });
await client.mutate("POST /users/$id/screen", { id });
```

No generated method tree, no operation-name guessing, no manual cache-key helpers. The string is the backend route: method plus file path, with `$params` preserved.

## The Contract

For:

```python
# src/app/routes/users/$id.py
from causeway import get, raises

@get
@raises(NotFound)
async def show(id: UUID) -> User: ...
```

Causeway derives:

| Field     | Value             |
| --------- | ----------------- |
| HTTP path | `/users/{id}`     |
| Route key | `GET /users/$id`  |
| Kind      | query             |
| Input     | `{ id: string }`  |
| Data      | `User`            |
| Error     | `NotFound` branch |

The generated types look like this:

```ts
export type QueryRouteKey = "GET /users/$id";
export type MutationRouteKey = "POST /users/$id/screen";
export type RouteKey = QueryRouteKey | MutationRouteKey;

export interface RouteContracts {
  "GET /users/$id": {
    input: { id: string };
    data: User;
    error: NotFound;
  };
}

export type RouteInput<K extends RouteKey> = RouteContracts[K]["input"];
export type RouteData<K extends RouteKey> = RouteContracts[K]["data"];
export type RouteError<K extends RouteKey> = RouteContracts[K]["error"];
```

The generated client's `query` and `refresh` methods only accept `QueryRouteKey`; `mutate` only accepts `MutationRouteKey`. The compiler catches the mistake before the request exists.

The generated type file also registers those contracts with `@causewayjs/client`, so framework adapters infer from the same route key:

```tsx
const customer = useQuery("GET /users/$id", { id });
customer.data?.name;
```

No `useQuery<User>(...)`, no separate operation type import.

## How It Is Generated

1. The file router walks `src/app/routes/`.
2. Method decorators stamp handlers with `GET`, `POST`, `PATCH`, etc.
3. The router derives the HTTP path, public route key, source file, route-group scopes, middleware, providers, and route-contract metadata.
4. The runtime turns each handler signature into IR: params, body, response, declared errors, streams.
5. The generator writes the browser metadata and typed client facade.

The generated client entry exposes:

```ts
export function createClient(options?: ClientOptions): Client;
export { routeMeta, loadRoute };
export type {
  RouteKey,
  QueryRouteKey,
  MutationRouteKey,
  RouteInput,
  RouteData,
  RouteError,
};
```

## Core Client

```ts
import { createClient } from "./generated/client";

const client = createClient({
  baseUrl: "https://api.example.com",
  headers: () => ({ authorization: `Bearer ${token}` }),
});

const customer = await client.query("GET /customers/$id", { id });
const screening = await client.mutate("POST /customers/$id/screen", { id });
```

The owned runtime handles:

- Stable query keys: route key + canonical input + scope.
- Inline input objects without accidental refetch loops.
- In-flight query dedupe.
- Abort signals.
- Hydration and dehydration.
- `CausewayError` for typed `@raises` errors and plain HTTP failures.
- Mutation state and backend-declared refreshes.

## Refreshes

Mutations can declare the queries they refresh:

```python
# src/app/routes/customers/$id/screen.py
from causeway import post

@post(refreshes=("GET /customers/$id", "GET /customers"))
async def screen(id: UUID) -> Screening: ...
```

After this succeeds:

```ts
await client.mutate("POST /customers/$id/screen", { id });
```

the client refreshes cached queries matching `"GET /customers/$id"` and `"GET /customers"` using the mutation input where the query can be satisfied. Failed mutations do not refresh.

This is intentionally small. Causeway does not add `changes=...`, resource keys, or a second invalidation naming system in v1.

## Framework Adapters

Every adapter uses the same generated route-key client:

| Framework | Guide                | Surface                                           |
| --------- | -------------------- | ------------------------------------------------- |
| React     | [React](./react.md)  | `CausewayProvider`, `useQuery`, `useMutation`     |
| Next.js   | [Next.js](./next.md) | server client, `prefetch`, `dehydrate`, `hydrate` |

The runtime behavior is shared: stable query keys, dedupe, aborts, typed errors, hydration, and backend-declared `refreshes`.

## Streaming

```python
from causeway import get, stream

@get
async def watch(thread_id: str) -> stream[Event]: ...
```

```ts
for await (const event of client.stream("GET /watch", { threadId })) {
  // event is RouteData<"GET /watch">
}
```

## Production Build

```bash
causeway build
# dist/
#   ir.json
#   client/
#     index.ts
#     types.d.ts
#     meta.ts
#     routes/
#   my_app-0.0.1-py3-none-any.whl
```

Ship `client/` to your frontend and the wheel to your backend runtime.
