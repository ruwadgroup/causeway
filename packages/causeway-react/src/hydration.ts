// Dev-only hydration bookkeeping. When the server prefetches a query, we record
// the route key + input it hydrated under so that, if a client `useQuery` mounts
// with a mismatched input (a common SSR footgun), we can warn precisely instead
// of silently refetching. All of this is compiled out in production.

import type { CausewayClient, DehydratedClient, RouteInputValue } from "@causewayjs/client";

import { isBrowserRuntime, isDevRuntime } from "./runtime-env.js";

const HYDRATED_QUERIES = "__CAUSEWAY_HYDRATED_QUERIES__";

interface HydratedQueryRecord {
  client: CausewayClient;
  routeKey: string;
  input: RouteInputValue;
  key: string;
}

interface CausewayGlobal {
  [HYDRATED_QUERIES]?: HydratedQueryRecord[];
}

export function registerCausewayHydrationSnapshot(
  client: CausewayClient,
  snapshot: DehydratedClient,
): void {
  if (!isDevRuntime() || !isBrowserRuntime()) return;
  const root = globalThis as CausewayGlobal;
  const current = root[HYDRATED_QUERIES] ?? [];
  root[HYDRATED_QUERIES] = [
    ...current,
    ...snapshot.queries.map((query) => ({
      client,
      routeKey: query.routeKey,
      input: query.input,
      key: client.queryKey(query.routeKey, query.input),
    })),
  ];
}

export function warnOnHydrationKeyMismatch(
  client: CausewayClient,
  routeKey: string,
  input: RouteInputValue,
  stableKey: string,
  data: unknown,
): void {
  if (!isDevRuntime() || !isBrowserRuntime() || data !== undefined) return;
  const hydrated = (globalThis as CausewayGlobal)[HYDRATED_QUERIES] ?? [];
  const mismatch = hydrated.find(
    (query) => query.client === client && query.routeKey === routeKey && query.key !== stableKey,
  );
  if (mismatch === undefined) return;
  console.warn(
    [
      `Causeway useQuery("${routeKey}") did not match a hydrated server snapshot.`,
      `Prefetched input: ${formatDevValue(mismatch.input)}.`,
      `Hook input: ${formatDevValue(input)}.`,
      "Use the same route key and input shape for prefetch(...) and useQuery(...).",
    ].join(" "),
  );
}

function formatDevValue(value: unknown): string {
  if (value === undefined) return "undefined";
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
