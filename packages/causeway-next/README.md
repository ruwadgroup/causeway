# @causewayjs/next

Next.js helpers for the Causeway route-key client.

```bash
pnpm add @causewayjs/next @causewayjs/client
```

```tsx
"use client";

import { createHydrateClient } from "@causewayjs/next/client";
import { createClient } from "./client";

export const HydrateClient = createHydrateClient(createClient, {
  baseUrl: "/api",
});
```

```ts
// causeway-server.ts
import { createServerHydration } from "@causewayjs/next";
import { headers } from "next/headers";
import { HydrateClient } from "./causeway-client";
import { createClient } from "./client";

export async function getServerHydration() {
  return createServerHydration(createClient, {
    baseUrl: process.env.CAUSEWAY_API_URL,
    headers: await headers(),
    HydrateClient,
  });
}
```

```tsx
import { getServerHydration } from "./causeway-server";

const causeway = await getServerHydration();

await causeway.prefetch("GET /customers/$id", { id });

return causeway.hydrate(<CustomerPage id={id} />);
```

The helpers keep request headers request-scoped, provide small hydration wrappers, and expose idempotency header defaults for mutation calls.

The default shape mirrors the React Query hydration flow: prefetch into a server client, then render a hydration boundary without passing cache state through every page. Most apps should hide `createServerHydration(createClient, { headers, HydrateClient, ... })` behind a local `getServerHydration()` helper. Lower-level helpers are still available: `createServerClient(createClient, ...)`, `prefetch`, `prefetchMany`, `dehydrate`, `hydrate`, and `queryOptions`.

Boundary rule: keep one persistent browser client at the app root, then render the `causeway.HydrateClient` returned from every server layout/page helper that calls `causeway.prefetch(...)`. Nested boundaries are expected; each one merges its snapshot into the nearest parent client during App Router navigations. In development, Causeway warns when a prefetched server scope never renders its boundary or when a hydrated route key does not match a client hook's query input.

Use this package on the server side of a Next app. The generated client and `@causewayjs/react` still own the browser-side hooks.

## Docs

See the full Next.js guide in the Causeway docs: <https://github.com/ruwadgroup/causeway/blob/main/docs/client/next.md>.

## License

MIT
