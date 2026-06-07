# First Product Slice

This page shows the Causeway happy path in one realistic slice: a customer detail route, a special action, backend-declared refreshes, and a React screen.

The goal is not to build a full CRM. The goal is to see the shape.

## 1. Create the Route Files

```
src/app/routes/
└── customers/
    ├── index.py              # GET /customers
    └── $id/
        ├── index.py          # GET /customers/{id}
        └── screen.py         # POST /customers/{id}/screen
```

Causeway derives these route keys:

| File                      | Handler | Route key                    |
| ------------------------- | ------- | ---------------------------- |
| `customers/index.py`      | `@get`  | `GET /customers`             |
| `customers/$id/index.py`  | `@get`  | `GET /customers/$id`         |
| `customers/$id/screen.py` | `@post` | `POST /customers/$id/screen` |

The HTTP path uses `{id}`. The client key keeps `$id`, matching the tree you read and edit.

## 2. Add the Query Routes

```python
# src/app/routes/customers/index.py
from msgspec import Struct
from causeway import get


class CustomerSummary(Struct):
    id: str
    name: str
    risk: str


@get
async def list_customers() -> list[CustomerSummary]:
    return [
        CustomerSummary(id="cus_1", name="Ada Lovelace", risk="low"),
        CustomerSummary(id="cus_2", name="Grace Hopper", risk="review"),
    ]
```

```python
# src/app/routes/customers/$id/index.py
from causeway import get, raises
from causeway.errors import NotFound
from msgspec import Struct


class Customer(Struct):
    id: str
    name: str
    risk: str
    screened: bool


@get
@raises(NotFound)
async def show(id: str) -> Customer:
    if id == "missing":
        raise NotFound(f"customer {id}")
    return Customer(id=id, name="Ada Lovelace", risk="low", screened=False)
```

The handler signature is the contract. `id: str` becomes route input, `-> Customer` becomes route data, and `@raises(NotFound)` becomes the typed route error.

## 3. Add a Special Action

```python
# src/app/routes/customers/$id/screen.py
from causeway import post, raises
from causeway.errors import NotFound
from msgspec import Struct


class ScreeningResult(Struct):
    id: str
    screened: bool
    risk: str


@post(refreshes=("GET /customers/$id", "GET /customers"))
@raises(NotFound)
async def screen(id: str) -> ScreeningResult:
    if id == "missing":
        raise NotFound(f"customer {id}")
    return ScreeningResult(id=id, screened=True, risk="low")
```

`refreshes` is the only explicit cache/update contract in v1. The mutation knows it changes the customer detail and list views, so that knowledge lives beside the mutation.

After `POST /customers/$id/screen` succeeds, the client refreshes cached `GET /customers/$id` and `GET /customers` queries. Failed mutations do not refresh.

## 4. Inspect What Causeway Sees

Run the app:

```bash
uv run causeway dev
```

Inspect the route table:

```bash
uv run causeway inspect
uv run causeway inspect --json
```

In dev you can also open:

```text
http://127.0.0.1:8000/__causeway
http://127.0.0.1:8000/__causeway/graph
```

The App Graph should show the route keys, source files, declared errors, and refresh contract.

## 5. Generate the Client

```bash
uv run causeway codegen --out src/lib/causeway/client
```

The generated client exposes route-key types:

```ts
import { createClient } from "./causeway/client";

const client = createClient({ baseUrl: "http://127.0.0.1:8000" });

const customer = await client.query("GET /customers/$id", { id: "cus_1" });
await client.mutate("POST /customers/$id/screen", { id: "cus_1" });
```

If you call `client.query("POST /customers/$id/screen", ...)`, TypeScript complains. Queries are GET routes. Mutations are non-GET routes.

## 6. Use It from React

```tsx
import { CausewayProvider, useMutation, useQuery } from "@causewayjs/react";
import { createClient } from "./causeway/client";

const client = createClient({ baseUrl: "/api" });

export function Providers({ children }: { children: React.ReactNode }) {
  return <CausewayProvider client={client}>{children}</CausewayProvider>;
}

export function CustomerScreen({ id }: { id: string }) {
  const customer = useQuery("GET /customers/$id", { id });

  const screen = useMutation("POST /customers/$id/screen", {
    feedback: {
      loading: "Screening customer...",
      success: "Customer screened",
    },
  });

  if (customer.pending) return <p>Loading...</p>;
  if (customer.error) return <p>Could not load customer.</p>;

  return (
    <section>
      <h1>{customer.data?.name}</h1>
      <p>Risk: {customer.data?.risk}</p>
      <button disabled={screen.pending} onClick={() => screen({ id })}>
        Screen
      </button>
    </section>
  );
}
```

There are no manual query-key helpers and no frontend invalidation list. The backend mutation declared the refresh contract, and the client runtime runs it after success.

## Where to Go Next

- [Defining routes](../backend/routing.md) — full file routing rules.
- [HTTP methods](../backend/methods.md) — decorators and refresh contracts.
- [Client runtime](../client/index.md) — route-key client details.
- [React](../client/react.md), [Next.js](../client/next.md) — framework adapters.
- [App Graph](../client/app-graph.md) — what `causeway inspect --json` exposes.
