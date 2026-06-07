// The route-key client: a tiny query cache + request orchestrator that the
// framework bindings (`@causewayjs/react`, `@causewayjs/next`) sit on top of.
// Wire encoding, SSE, and case conversion live in sibling modules; this file
// owns identity (cache keys), in-flight dedup, refresh-after-mutation, and
// dehydrate/hydrate.

import { buildRequest, streamCall, unaryCall } from "./transport.js";
import type {
  CallOptions,
  CausewayClient,
  ClientConfig,
  DehydratedClient,
  HydrateOptions,
  QueryState,
  RouteDescriptor,
  RouteInputValue,
  RouteMeta,
} from "./types.js";
import { unwrapResult } from "./types.js";
import { argsFromInput, isAbortError, stableStringify } from "./utils.js";

const EMPTY_QUERY_STATE: QueryState = Object.freeze({ error: null, pending: false });

// Sentinel returned by `projectRefreshInput` when a parameterized refresh
// can't be satisfied from the mutation's input — we skip it rather than fire a
// request with a missing path param.
const SKIP_REFRESH = Symbol("causeway.skipRefresh");
type ProjectedRefreshInput = RouteInputValue | typeof SKIP_REFRESH;

interface QueryEntry {
  routeKey: string;
  input: RouteInputValue;
  scope: unknown;
  state: QueryState;
}

export function createRouteKeyClient(config: ClientConfig): CausewayClient {
  const baseUrl = (config.baseUrl ?? "").replace(/\/$/, "");
  const fetchImpl = config.fetch ?? globalThis.fetch.bind(globalThis);
  const descriptorCache = new Map<string, Promise<RouteDescriptor>>();
  const metaByRouteKey = new Map<string, RouteMeta>();
  const entries = new Map<string, QueryEntry>();
  const inFlight = new Map<string, Promise<unknown>>();
  const listeners = new Map<string, Set<() => void>>();
  const scope = config.scope ?? null;

  for (const route of config.routeMeta) {
    metaByRouteKey.set(route.routeKey, route);
  }

  const loadRoute = (id: string): Promise<RouteDescriptor> => {
    let cached = descriptorCache.get(id);
    if (cached === undefined) {
      cached = Promise.resolve(config.loadRoute(id));
      descriptorCache.set(id, cached);
    }
    return cached;
  };

  const fetchRoute = async (
    routeKey: string,
    input: RouteInputValue,
    opts: CallOptions,
    kind: "query" | "mutation",
  ): Promise<unknown> => {
    const meta = requireRouteMeta(metaByRouteKey, routeKey);
    assertRouteKind(meta, kind);
    const descriptor = await loadRoute(meta.id);
    const { url, init } = buildRequest(
      descriptor,
      argsFromInput(input),
      opts,
      baseUrl,
      config.headers,
    );
    return unwrapResult(await unaryCall(descriptor, url, init, fetchImpl));
  };

  const client: CausewayClient = {
    async query<TData = unknown>(
      routeKey: string,
      input?: RouteInputValue,
      opts: CallOptions = {},
    ): Promise<TData> {
      const key = cacheKey(routeKey, input, scope);
      const cached = entries.get(key);
      if (cached?.state.data !== undefined && !cached.state.pending) {
        return cached.state.data as TData;
      }
      return (await runQuery(routeKey, input, opts, false)) as TData;
    },
    async refresh<TData = unknown>(
      routeKey: string,
      input?: RouteInputValue,
      opts: CallOptions = {},
    ): Promise<TData> {
      return (await runQuery(routeKey, input, opts, true)) as TData;
    },
    async mutate<TData = unknown>(
      routeKey: string,
      input?: RouteInputValue,
      opts: CallOptions = {},
    ): Promise<TData> {
      const data = await fetchRoute(routeKey, input, opts, "mutation");
      const meta = metaByRouteKey.get(routeKey);
      const descriptor = meta === undefined ? undefined : await loadRoute(meta.id);
      const refreshes = descriptor?.refreshes ?? meta?.refreshes ?? [];
      await Promise.all(refreshes.map((key) => refreshAfterMutation(key, input, opts)));
      return data as TData;
    },
    stream<TEvent = unknown>(
      routeKey: string,
      input?: RouteInputValue,
      opts: CallOptions = {},
    ): AsyncIterable<TEvent> {
      return streamRoute<TEvent>(routeKey, input, opts);
    },
    getData<TData = unknown>(routeKey: string, input?: RouteInputValue) {
      return entries.get(cacheKey(routeKey, input, scope))?.state.data as TData | undefined;
    },
    setData(routeKey, input, data) {
      const key = cacheKey(routeKey, input, scope);
      entries.set(key, {
        routeKey,
        input: input ?? {},
        scope,
        state: { data, error: null, pending: false, updatedAt: Date.now() },
      });
      notify(listeners, key);
    },
    getQueryState<TData = unknown, TError = unknown>(routeKey: string, input?: RouteInputValue) {
      return (entries.get(cacheKey(routeKey, input, scope))?.state ??
        EMPTY_QUERY_STATE) as QueryState<TData, TError>;
    },
    subscribe(routeKey, input, listener) {
      const key = cacheKey(routeKey, input, scope);
      const bucket = listeners.get(key) ?? new Set<() => void>();
      bucket.add(listener);
      listeners.set(key, bucket);
      return () => {
        bucket.delete(listener);
        if (bucket.size === 0) listeners.delete(key);
      };
    },
    queryKey(routeKey, input) {
      return cacheKey(routeKey, input, scope);
    },
    dehydrate() {
      const queries = [...entries.values()]
        .filter((entry) => entry.state.data !== undefined)
        .map((entry) => ({
          routeKey: entry.routeKey,
          input: entry.input,
          scope: entry.scope,
          data: entry.state.data,
          updatedAt: entry.state.updatedAt ?? Date.now(),
        }));
      return { version: 1, id: snapshotId(queries), queries };
    },
    hydrate(snapshot: DehydratedClient, options: HydrateOptions = {}) {
      if (snapshot.version !== 1) return;
      const shouldNotify = options.notify !== false;
      for (const query of snapshot.queries) {
        const key = cacheKey(query.routeKey, query.input, query.scope);
        const previous = entries.get(key);
        const nextState: QueryState = {
          data: query.data,
          error: null,
          pending: false,
          updatedAt: query.updatedAt,
        };
        entries.set(key, {
          routeKey: query.routeKey,
          input: query.input,
          scope: query.scope,
          state: nextState,
        });
        if (
          shouldNotify &&
          (options.forceNotify === true || !queryStatesEqual(previous?.state, nextState))
        ) {
          notify(listeners, key);
        }
      }
    },
  };

  async function refreshAfterMutation(
    routeKey: string,
    mutationInput: RouteInputValue | undefined,
    opts: CallOptions,
  ): Promise<void> {
    try {
      const refreshInput = await projectRefreshInput(routeKey, mutationInput);
      if (refreshInput === SKIP_REFRESH) return;
      await client.refresh(routeKey, refreshInput, opts);
    } catch {
      // A mutation has already succeeded by the time refreshes run. Keep the
      // write result intact and let the refreshed query cache carry its error.
    }
  }

  // Map a mutation's input onto the refreshed query's parameters. Only the
  // params the refresh route declares are carried over; if a required path
  // param is absent we bail (SKIP_REFRESH) instead of firing a broken request.
  async function projectRefreshInput(
    routeKey: string,
    mutationInput: RouteInputValue | undefined,
  ): Promise<ProjectedRefreshInput> {
    const meta = requireRouteMeta(metaByRouteKey, routeKey);
    const descriptor = await loadRoute(meta.id);
    const params = descriptor.params ?? [];
    if (params.length === 0) return undefined;

    const source = argsFromInput(mutationInput);
    const input: Record<string, unknown> = {};
    for (const param of params) {
      if (param.in === "path" && source[param.name] == null) return SKIP_REFRESH;
      if (param.name in source) input[param.name] = source[param.name];
    }
    return input;
  }

  async function runQuery(
    routeKey: string,
    input: RouteInputValue,
    opts: CallOptions,
    force: boolean,
  ): Promise<unknown> {
    const key = cacheKey(routeKey, input, scope);
    if (!force) {
      const pending = inFlight.get(key);
      if (pending !== undefined) return await pending;
    }

    const previous = entries.get(key);
    const keepPreviousData = opts.cache !== "no-store";
    entries.set(key, {
      routeKey,
      input: input ?? {},
      scope,
      state: {
        data: keepPreviousData ? previous?.state.data : undefined,
        error: null,
        pending: true,
        updatedAt: previous?.state.updatedAt,
      },
    });
    notify(listeners, key);

    const request = fetchRoute(routeKey, input, opts, "query")
      .then((data) => {
        entries.set(key, {
          routeKey,
          input: input ?? {},
          scope,
          state: { data, error: null, pending: false, updatedAt: Date.now() },
        });
        notify(listeners, key);
        return data;
      })
      .catch((error: unknown) => {
        // An aborted request should restore the prior cache state, not record
        // an error — the caller cancelled deliberately.
        if (isAbortError(error)) {
          if (previous === undefined) entries.delete(key);
          else entries.set(key, previous);
          notify(listeners, key);
          throw error;
        }
        entries.set(key, {
          routeKey,
          input: input ?? {},
          scope,
          state: {
            data: keepPreviousData ? previous?.state.data : undefined,
            error,
            pending: false,
            updatedAt: previous?.state.updatedAt,
          },
        });
        notify(listeners, key);
        throw error;
      })
      .finally(() => {
        inFlight.delete(key);
      });

    inFlight.set(key, request);
    return await request;
  }

  async function* streamRoute<TEvent>(
    routeKey: string,
    input: RouteInputValue,
    opts: CallOptions,
  ): AsyncIterableIterator<TEvent> {
    const meta = requireRouteMeta(metaByRouteKey, routeKey);
    const descriptor = await loadRoute(meta.id);
    if (!meta.streams && !descriptor.streams) {
      throw new Error(`Causeway route is not a stream: ${routeKey}`);
    }
    yield* streamCall(
      descriptor,
      argsFromInput(input),
      opts,
      baseUrl,
      config.headers,
      fetchImpl,
    ) as AsyncIterableIterator<TEvent>;
  }

  return client;
}

function requireRouteMeta(routes: Map<string, RouteMeta>, routeKey: string): RouteMeta {
  const meta = routes.get(routeKey);
  if (meta === undefined) throw new Error(`Unknown causeway route key: ${routeKey}`);
  return meta;
}

function assertRouteKind(route: RouteMeta, kind: "query" | "mutation"): void {
  const isQuery = route.method === "GET";
  if (kind === "query" && !isQuery) {
    throw new Error(`Causeway query routes must be GET: ${route.routeKey}`);
  }
  if (kind === "mutation" && isQuery) {
    throw new Error(`Causeway mutation routes must not be GET: ${route.routeKey}`);
  }
}

// Cache identity: route key + canonical input + scope. `stableStringify`
// sorts object keys so `{a,b}` and `{b,a}` collide intentionally.
function cacheKey(routeKey: string, input: unknown, scope: unknown): string {
  return stableStringify([routeKey, input ?? {}, scope ?? null]);
}

// Content signature over route key + input + updatedAt, excluding the (large)
// data payload — framework bindings key hydration on this to skip no-op work.
function snapshotId(
  queries: ReadonlyArray<{ routeKey: string; input: unknown; updatedAt: number }>,
): string {
  if (queries.length === 0) return "0";
  let sig = String(queries.length);
  for (const q of queries) sig += `|${q.routeKey}#${stableStringify(q.input)}@${q.updatedAt}`;
  return sig;
}

function notify(listeners: Map<string, Set<() => void>>, key: string): void {
  const bucket = listeners.get(key);
  if (bucket === undefined) return;
  for (const listener of bucket) listener();
}

function queryStatesEqual(left: QueryState | undefined, right: QueryState): boolean {
  return (
    left !== undefined &&
    left.error === right.error &&
    left.pending === right.pending &&
    left.updatedAt === right.updatedAt &&
    stableStringify(left.data) === stableStringify(right.data)
  );
}
