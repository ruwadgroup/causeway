import { parseSSE } from "./sse.js";
import { buildError, CausewayError, unwrapResult } from "./types.js";
import type {
  CallOptions,
  CausewayClient,
  ClientConfig,
  DehydratedClient,
  HydrateOptions,
  QueryState,
  Result,
  RouteDescriptor,
  RouteMeta,
} from "./types.js";

type Args = Record<string, unknown>;
type FetchImpl = typeof globalThis.fetch;
const EMPTY_QUERY_STATE: QueryState = Object.freeze({ error: null, pending: false });

interface QueryEntry {
  routeKey: string;
  input: unknown;
  scope: unknown;
  state: QueryState;
}

export function createRouteKeyClient(config: ClientConfig): CausewayClient {
  const baseUrl = (config.baseUrl ?? "").replace(/\/$/, "");
  const fetchImpl: FetchImpl = config.fetch ?? globalThis.fetch.bind(globalThis);
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
    input: Record<string, unknown> | void,
    opts: CallOptions,
    kind: "query" | "mutation",
  ): Promise<unknown> => {
    const meta = requireRouteMeta(metaByRouteKey, routeKey);
    assertRouteKind(meta, kind);
    const descriptor = await loadRoute(meta.id);
    const { url, init } = buildRequest(
      descriptor,
      (input ?? {}) as Args,
      opts,
      baseUrl,
      config.headers,
    );
    return unwrapResult(await unaryCall(descriptor, url, init, fetchImpl));
  };

  const client: CausewayClient = {
    async query<TData = unknown>(
      routeKey: string,
      input?: Record<string, unknown> | void,
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
      input?: Record<string, unknown> | void,
      opts: CallOptions = {},
    ): Promise<TData> {
      return (await runQuery(routeKey, input, opts, true)) as TData;
    },
    async mutate<TData = unknown>(
      routeKey: string,
      input?: Record<string, unknown> | void,
      opts: CallOptions = {},
    ): Promise<TData> {
      const data = await fetchRoute(routeKey, input, opts, "mutation");
      const meta = metaByRouteKey.get(routeKey);
      const descriptor = meta === undefined ? undefined : await loadRoute(meta.id);
      const refreshes = descriptor?.refreshes ?? meta?.refreshes ?? [];
      await Promise.all(
        refreshes.map(async (key) => {
          const refreshInput = await projectRefreshInput(key, input);
          return await client.refresh(key, refreshInput, opts);
        }),
      );
      return data as TData;
    },
    stream<TEvent = unknown>(
      routeKey: string,
      input?: Record<string, unknown> | void,
      opts: CallOptions = {},
    ): AsyncIterable<TEvent> {
      return streamRoute<TEvent>(routeKey, input, opts);
    },
    getData<TData = unknown>(routeKey: string, input?: Record<string, unknown> | void) {
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
    getQueryState<TData = unknown, TError = unknown>(
      routeKey: string,
      input?: Record<string, unknown> | void,
    ) {
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
      return {
        version: 1,
        queries: [...entries.values()]
          .filter((entry) => entry.state.data !== undefined)
          .map((entry) => ({
            routeKey: entry.routeKey,
            input: entry.input,
            scope: entry.scope,
            data: entry.state.data,
            updatedAt: entry.state.updatedAt ?? Date.now(),
          })),
      };
    },
    hydrate(snapshot: DehydratedClient, options: HydrateOptions = {}) {
      if (snapshot.version !== 1) return;
      const shouldNotify = options.notify !== false;
      for (const query of snapshot.queries) {
        const key = cacheKey(query.routeKey, query.input, query.scope);
        const previous = entries.get(key);
        const nextState = {
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

  async function projectRefreshInput(
    routeKey: string,
    mutationInput: Record<string, unknown> | void | undefined,
  ): Promise<Record<string, unknown> | void> {
    const meta = requireRouteMeta(metaByRouteKey, routeKey);
    const descriptor = await loadRoute(meta.id);
    const params = descriptor.params ?? [];
    if (params.length === 0) return undefined;
    const source = (mutationInput ?? {}) as Record<string, unknown>;
    const input: Record<string, unknown> = {};
    for (const param of params) {
      if (param.name in source) input[param.name] = source[param.name];
    }
    return input;
  }

  async function runQuery(
    routeKey: string,
    input: Record<string, unknown> | void,
    opts: CallOptions,
    force: boolean,
  ): Promise<unknown> {
    const key = cacheKey(routeKey, input, scope);
    if (!force) {
      const pending = inFlight.get(key);
      if (pending !== undefined) return await pending;
    }

    const previous = entries.get(key);
    entries.set(key, {
      routeKey,
      input: input ?? {},
      scope,
      state: {
        data: previous?.state.data,
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
        entries.set(key, {
          routeKey,
          input: input ?? {},
          scope,
          state: {
            data: previous?.state.data,
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
    input: Record<string, unknown> | void,
    opts: CallOptions,
  ): AsyncIterableIterator<TEvent> {
    const meta = requireRouteMeta(metaByRouteKey, routeKey);
    const descriptor = await loadRoute(meta.id);
    if (!meta.streams && !descriptor.streams) {
      throw new Error(`Causeway route is not a stream: ${routeKey}`);
    }
    yield* streamCall(
      descriptor,
      (input ?? {}) as Args,
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

function cacheKey(routeKey: string, input: unknown, scope: unknown): string {
  return stableStringify([routeKey, input ?? {}, scope ?? null]);
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

function stableStringify(value: unknown): string {
  return JSON.stringify(canonicalize(value));
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!isPlainObject(value)) return value;
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(value).sort()) out[key] = canonicalize(value[key]);
  return out;
}

function buildRequest(
  route: RouteDescriptor,
  args: Args,
  opts: CallOptions,
  baseUrl: string,
  defaultHeaders: Record<string, string> | undefined,
): { url: string; init: RequestInit } {
  let { path } = route;
  const query = new URLSearchParams();
  const headers: Record<string, string> = { ...defaultHeaders, ...opts.headers };

  const bodyEmbed: Record<string, unknown> = {};
  let bodyWhole: unknown;
  let bodyMode: "none" | "json" | "multipart" | "binary" | "form" = "none";
  let multipart: FormData | null = null;

  for (const p of route.params ?? []) {
    const v = args[p.name];
    if (v === undefined || (p.in === "query" && v === null)) continue;
    switch (p.in) {
      case "path": {
        path = path.replace(`{${p.alias}}`, encodeURIComponent(String(v)));
        break;
      }
      case "query": {
        // Arrays expand to repeated keys: ?tag=a&tag=b. Servers using
        // request.query_params.getlist(...) recover the list.
        if (Array.isArray(v)) {
          for (const item of v) {
            if (item !== null && item !== undefined) query.append(p.alias, String(item));
          }
        } else query.append(p.alias, String(v));
        break;
      }
      case "header": {
        headers[p.alias] = String(v);
        break;
      }
      case "cookie": {
        // Browsers won't let JS set Cookie directly — userland can override.
        const prev = headers["cookie"];
        headers["cookie"] = `${prev ? `${prev}; ` : ""}${p.alias}=${String(v)}`;
        break;
      }
      case "file": {
        if (multipart == null) multipart = new FormData();
        multipart.append(p.alias, v instanceof Blob ? v : String(v));
        bodyMode = "multipart";
        break;
      }
      case "body": {
        if (route.binaryBody) {
          // Raw-bytes body — pass the value through unchanged.
          bodyWhole = v;
          bodyMode = "binary";
        } else if (route.formBody) {
          bodyWhole = v;
          bodyMode = "form";
        } else if (p.embed) {
          bodyEmbed[p.alias] = v;
          if (bodyMode === "none") bodyMode = "json";
        } else {
          bodyWhole = v;
          if (bodyMode === "none") bodyMode = "json";
        }
        break;
      }
    }
  }

  let body: BodyInit | undefined;
  const requestOpaque = buildOpaqueTree(route.opaqueRequestPaths);
  if (bodyMode === "json") {
    headers["content-type"] ??= "application/json";
    const payload = Object.keys(bodyEmbed).length > 0 ? bodyEmbed : bodyWhole;
    // camelCase → snake_case so the Python server sees the keys it expects.
    // Subtrees flagged opaque in the route descriptor pass through untouched
    // so user-defined JSON (e.g. `definition: dict[str, Any]`) keeps its keys.
    body =
      payload === undefined
        ? undefined
        : JSON.stringify(camelToSnakeDeepGuarded(payload, requestOpaque));
  } else if (bodyMode === "multipart" && multipart != null) {
    // Let fetch set the multipart boundary; we must NOT pin content-type.
    delete headers["content-type"];
    body = multipart;
  } else if (bodyMode === "binary") {
    headers["content-type"] ??= "application/octet-stream";
    body = bodyWhole as BodyInit;
  } else if (bodyMode === "form") {
    headers["content-type"] ??= "application/x-www-form-urlencoded";
    const form = new URLSearchParams();
    const payload = camelToSnakeDeepGuarded(bodyWhole, requestOpaque);
    if (!isPlainObject(payload)) {
      throw new TypeError("Causeway form body must be an object.");
    }
    for (const [k, val] of Object.entries(payload)) {
      if (val === undefined || val === null) continue;
      if (Array.isArray(val)) for (const item of val) form.append(k, String(item));
      else form.append(k, String(val));
    }
    body = form.toString();
  }

  const qs = query.toString();
  return {
    url: `${baseUrl}${path}${qs ? `?${qs}` : ""}`,
    init: { method: route.method, headers, body, signal: opts.signal },
  };
}

async function unaryCall(
  route: RouteDescriptor,
  url: string,
  init: RequestInit,
  fetchImpl: FetchImpl,
): Promise<unknown> {
  const res = await fetchImpl(url, init);

  if (route.binaryResponse) {
    if (!res.ok) throw await httpError(res);
    // Server marked the route as raw bytes — hand back a Blob, skip JSON parsing.
    return await res.blob();
  }

  const ct = res.headers.get("content-type") ?? "";

  // JSON path — covers both 2xx envelopes and 4xx/5xx typed-error envelopes
  // ({ ok: false, error: { kind, … } }). Frameworks like Causeway map declared
  // `@raises` errors to their HTTP status code while keeping the envelope body;
  // we recognize that shape and surface it as `Result.error` instead of a
  // generic `HTTP NNN: …` so consumers can branch on `error.kind`.
  if (ct.includes("application/json")) {
    const raw: unknown = await res.json();
    const responseOpaque = buildOpaqueTree(route.opaqueResponsePaths);
    const value = snakeToCamelDeepGuarded(raw, responseOpaque);
    if (isTypedErrorEnvelope(value)) {
      if (route.result) return value as Result<unknown, unknown>;
      const errPayload = value.error;
      // Carry the HTTP status onto the thrown error so consumers don't need
      // to inspect the response separately.
      throw buildError({ ...errPayload, status: errPayload.status ?? res.status });
    }
    if (!res.ok) throw httpErrorFromJson(res.status, raw);
    // `result: true` hands the envelope back untouched; the caller's static
    // type is `Result<T, E>` so TypeScript forces them to branch on `ok`.
    return route.result ? (value as Result<unknown, unknown>) : value;
  }

  if (!res.ok) throw await httpError(res);
  if (res.status === 204 || ct === "") return undefined;
  return await res.text();
}

function isTypedErrorEnvelope(
  value: unknown,
): value is { ok: false; error: Record<string, unknown> & { kind: string } } {
  if (!isPlainObject(value) || value.ok !== false) return false;
  const { error } = value;
  return isPlainObject(error) && typeof error.kind === "string";
}

function httpErrorFromJson(status: number, raw: unknown): CausewayError {
  if (isPlainObject(raw)) {
    return buildError({ ...raw, status });
  }
  return new CausewayError({
    kind: "HttpError",
    status,
    message: `HTTP ${status}`,
    data: raw,
  });
}

// Streaming caller with built-in resume. We track the last `id:` seen and,
// if the connection drops mid-stream, reconnect with `Last-Event-Id`. The
// server's `retry:` value (in ms) controls the minimum backoff; we cap at
// 30s and abort on user cancellation.
async function* streamCall(
  route: RouteDescriptor,
  args: Args,
  opts: CallOptions,
  baseUrl: string,
  defaultHeaders: Record<string, string> | undefined,
  fetchImpl: FetchImpl,
): AsyncIterableIterator<unknown> {
  let lastId: string | undefined;
  let retryMs = 1000; // default backoff if server doesn't send `retry:`
  const startedAt = Date.now();
  const maxResumeWindowMs = 5 * 60 * 1000; // give up after 5 min of failed reconnects
  const streamOpaque = buildOpaqueTree(route.opaqueResponsePaths);

  while (true) {
    if (opts.signal?.aborted) return;
    const headers: Record<string, string> = { ...defaultHeaders, ...opts.headers };
    if (lastId !== undefined) headers["last-event-id"] = lastId;

    const { url, init } = buildRequest(route, args, { ...opts, headers }, baseUrl, defaultHeaders);
    let res: Response;
    try {
      res = await fetchImpl(url, init);
    } catch (error) {
      if (opts.signal?.aborted) return;
      if (Date.now() - startedAt > maxResumeWindowMs) throw error;
      await sleep(retryMs, opts.signal);
      continue;
    }
    if (!res.ok) throw await httpError(res);
    if (!res.body) return;

    let sawDone = false;
    try {
      for await (const ev of parseSSE(res.body)) {
        if (ev.retry !== undefined) retryMs = Math.min(ev.retry, 30_000);
        if (ev.id !== undefined) lastId = ev.id;
        if (ev.event === "done") {
          sawDone = true;
          return;
        }
        if (ev.event === "error") {
          // Typed stream errors are terminal — don't retry, propagate to caller.
          throw Object.assign(new Error("stream error"), {
            kind: "error",
            payload: safeJsonParse(ev.data),
            causewayTerminal: true,
          });
        }
        if (ev.data === "") continue;
        yield snakeToCamelDeepGuarded(safeJsonParse(ev.data), streamOpaque);
      }
    } catch (error) {
      if (opts.signal?.aborted) return;
      if (isTerminalStreamError(error)) throw error;
      if (Date.now() - startedAt > maxResumeWindowMs) throw error;
      await sleep(retryMs, opts.signal);
      continue;
    }
    // Stream ended without `event: done` — treat as a disconnect and reconnect.
    if (sawDone) return;
    if (opts.signal?.aborted) return;
    if (Date.now() - startedAt > maxResumeWindowMs) return;
    await sleep(retryMs, opts.signal);
  }
}

async function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return;
  await new Promise<void>((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      resolve();
    };
    const timer = setTimeout(finish, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        finish();
      },
      { once: true },
    );
  });
}

async function httpError(res: Response): Promise<CausewayError> {
  const body = await res.text();
  const parsed = safeJsonParse(body);
  if (isPlainObject(parsed) && "kind" in parsed) {
    return buildError({ ...parsed, status: res.status });
  }
  return new CausewayError({
    kind: "HttpError",
    status: res.status,
    message: `HTTP ${res.status}`,
    data: body,
  });
}

function isTerminalStreamError(error: unknown): boolean {
  return (
    (typeof error === "object" || typeof error === "function") &&
    error !== null &&
    Reflect.get(error, "causewayTerminal") === true
  );
}

function safeJsonParse(s: string): unknown {
  try {
    return JSON.parse(s);
  } catch {
    return s;
  }
}

// ---- snake_case ↔ camelCase ----
// Causeway runs Python (snake_case) on the wire and TS (camelCase) in the editor.
// We walk plain-object trees only — arrays of objects descend, scalars and class
// instances (Blob, Date, FormData, …) pass through untouched.

const camelCache = new Map<string, string>();
const snakeCache = new Map<string, string>();

function snakeToCamel(s: string): string {
  const hit = camelCache.get(s);
  if (hit !== undefined) return hit;
  const out = s.replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase());
  camelCache.set(s, out);
  return out;
}

function camelToSnake(s: string): string {
  const hit = snakeCache.get(s);
  if (hit !== undefined) return hit;
  const out = s.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`);
  snakeCache.set(s, out);
  return out;
}

function isPlainObject(x: unknown): x is Record<string, unknown> {
  return (
    Boolean(x) &&
    typeof x === "object" &&
    (Object.getPrototypeOf(x) === Object.prototype || Object.getPrototypeOf(x) === null)
  );
}

function snakeToCamelDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(snakeToCamelDeep);
  if (!isPlainObject(value)) return value;
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(value)) out[snakeToCamel(k)] = snakeToCamelDeep(value[k]);
  return out;
}

function camelToSnakeDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(camelToSnakeDeep);
  if (!isPlainObject(value)) return value;
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(value)) out[camelToSnake(k)] = camelToSnakeDeep(value[k]);
  return out;
}

// Opaque-subtree-aware variants. Routes declare opaque paths in their
// descriptor when they accept or return user-defined JSON payloads
// (`dict[str, Any]` / `JsonObject`). At each declared path we skip the
// recursive rename so the payload's own keys survive the round trip.

interface OpaqueTree {
  opaque?: boolean;
  children?: Record<string, OpaqueTree>;
}

function buildOpaqueTree(paths: ReadonlyArray<string> | undefined): OpaqueTree | null {
  if (!paths || paths.length === 0) return null;
  const root: OpaqueTree = {};
  for (const path of paths) {
    let node = root;
    for (const seg of path.split(".")) {
      if (!seg) continue;
      const children = node.children ?? (node.children = {});
      node = children[seg] ?? (children[seg] = {});
    }
    node.opaque = true;
  }
  return root;
}

function snakeToCamelDeepGuarded(value: unknown, tree: OpaqueTree | null): unknown {
  if (tree === null) return snakeToCamelDeep(value);
  // Arrays inherit the parent path — opaque paths are property-relative.
  if (Array.isArray(value)) return value.map((v) => snakeToCamelDeepGuarded(v, tree));
  if (!isPlainObject(value)) return value;
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(value)) {
    const renamed = snakeToCamel(k);
    const child = tree.children?.[renamed];
    if (child?.opaque) {
      // Preserve the opaque subtree verbatim — don't even rename inside it.
      out[renamed] = value[k];
    } else if (child) {
      out[renamed] = snakeToCamelDeepGuarded(value[k], child);
    } else {
      out[renamed] = snakeToCamelDeep(value[k]);
    }
  }
  return out;
}

function camelToSnakeDeepGuarded(value: unknown, tree: OpaqueTree | null): unknown {
  if (tree === null) return camelToSnakeDeep(value);
  if (Array.isArray(value)) return value.map((v) => camelToSnakeDeepGuarded(v, tree));
  if (!isPlainObject(value)) return value;
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(value)) {
    const child = tree.children?.[k];
    const renamed = camelToSnake(k);
    if (child?.opaque) {
      out[renamed] = value[k];
    } else if (child) {
      out[renamed] = camelToSnakeDeepGuarded(value[k], child);
    } else {
      out[renamed] = camelToSnakeDeep(value[k]);
    }
  }
  return out;
}
