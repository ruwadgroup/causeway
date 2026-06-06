// Shared types between the runtime and the generated client.

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export type ParamLocation = "path" | "query" | "body" | "header" | "cookie" | "file";

export interface ParamDescriptor {
  name: string;
  alias: string;
  in: ParamLocation;
  embed?: boolean;
}

export interface RouteDescriptor {
  method: HttpMethod;
  path: string;
  /** Public route-key identity, e.g. "GET /customers/$id". */
  routeKey: string;
  params?: ReadonlyArray<ParamDescriptor>;
  refreshes?: ReadonlyArray<string>;
  scopes?: ReadonlyArray<string>;
  streams?: boolean;
  result?: boolean;
  /** Body is raw bytes (Blob / Uint8Array / ArrayBuffer) — skip JSON envelope. */
  binaryBody?: boolean;
  /** Response is raw bytes — decode with `res.blob()` instead of `res.json()`. */
  binaryResponse?: boolean;
  /** Body is application/x-www-form-urlencoded (or multipart/form-data when files present). */
  formBody?: boolean;
  /**
   * Dotted property paths within the request body whose value is an opaque
   * JSON object (typed `dict[str, Any]` / `JsonObject` server-side). The
   * runtime skips `camelToSnakeDeep` recursion into those subtrees so
   * user-defined JSON payloads round-trip unchanged. Paths use camelCase
   * property names and are relative to the request-body JSON.
   */
  opaqueRequestPaths?: ReadonlyArray<string>;
  /**
   * Dotted property paths within the response payload whose value is an
   * opaque JSON object. The runtime skips `snakeToCamelDeep` recursion into
   * those subtrees. For routes returning `Result<T, E>` the paths are
   * pre-prefixed with `data.` so they apply to the success envelope.
   */
  opaqueResponsePaths?: ReadonlyArray<string>;
}

export interface RouteMeta {
  /** Stable generated route id used to lazy-load the full route descriptor. */
  id: string;
  /** Public route-key identity, e.g. "GET /customers/$id". */
  routeKey: string;
  method: HttpMethod;
  path: string;
  refreshes?: ReadonlyArray<string>;
  scopes?: ReadonlyArray<string>;
  /** Whether generated route functions expect an args object before options. */
  hasArgs?: boolean;
  streams?: boolean;
}

export interface ClientConfig {
  baseUrl?: string;
  routeMeta: ReadonlyArray<RouteMeta>;
  loadRoute: (id: string) => RouteDescriptor | Promise<RouteDescriptor>;
  fetch?: typeof globalThis.fetch;
  headers?: Record<string, string>;
  scope?: unknown;
}

export interface QueryState<TData = unknown, TError = unknown> {
  data?: TData;
  error: TError | null;
  pending: boolean;
  updatedAt?: number;
}

export interface DehydratedQuery {
  routeKey: string;
  input: unknown;
  scope: unknown;
  data: unknown;
  updatedAt: number;
}

export interface DehydratedClient {
  version: 1;
  /** Content signature; framework bindings key hydration on this. Always set by `dehydrate()`. */
  id?: string;
  queries: DehydratedQuery[];
}

export interface HydrateOptions {
  notify?: boolean;
  forceNotify?: boolean;
}

export interface CausewayClient {
  query<TData = unknown>(
    routeKey: string,
    input?: Record<string, unknown> | void,
    opts?: CallOptions,
  ): Promise<TData>;
  mutate<TData = unknown>(
    routeKey: string,
    input?: Record<string, unknown> | void,
    opts?: CallOptions,
  ): Promise<TData>;
  refresh<TData = unknown>(
    routeKey: string,
    input?: Record<string, unknown> | void,
    opts?: CallOptions,
  ): Promise<TData>;
  stream<TEvent = unknown>(
    routeKey: string,
    input?: Record<string, unknown> | void,
    opts?: CallOptions,
  ): AsyncIterable<TEvent>;
  getData<TData = unknown>(
    routeKey: string,
    input?: Record<string, unknown> | void,
  ): TData | undefined;
  setData<TData = unknown>(
    routeKey: string,
    input: Record<string, unknown> | void,
    data: TData,
  ): void;
  getQueryState<TData = unknown, TError = unknown>(
    routeKey: string,
    input?: Record<string, unknown> | void,
  ): QueryState<TData, TError>;
  subscribe(
    routeKey: string,
    input: Record<string, unknown> | void,
    listener: () => void,
  ): () => void;
  queryKey(routeKey: string, input?: Record<string, unknown> | void): string;
  dehydrate(): DehydratedClient;
  hydrate(snapshot: DehydratedClient, options?: HydrateOptions): void;
}

export interface CallOptions {
  cache?: "default" | "no-store";
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

export type Result<T, E> = { ok: true; data: T } | { ok: false; error: E };

/**
 * Real `Error` subclass thrown for both typed (`@raises`) errors and bare HTTP
 * failures. Carries the discriminator (`kind`) and any extra fields the server
 * emitted so callers can branch on `err.kind === "Conflict"` while still getting
 * `err.message`, `err instanceof Error`, and a proper stack trace.
 *
 * For typed errors the `kind` is the server's discriminator (`"Conflict"`,
 * `"NotFound"`, etc.); for HTTP failures with no envelope it falls back to
 * `"HttpError"`.
 */
export class CausewayError extends Error {
  readonly kind: string;
  readonly status?: number;
  readonly code?: string;
  /** Raw payload from the server — full original error object or response text. */
  readonly data?: unknown;

  constructor(init: {
    kind: string;
    message?: string;
    status?: number;
    code?: string;
    data?: unknown;
    /** Extra fields lifted onto the instance so `err.foo` matches the union shape. */
    extras?: Record<string, unknown>;
  }) {
    super(init.message ?? init.kind);
    this.name = "CausewayError";
    this.kind = init.kind;
    if (init.status !== undefined) this.status = init.status;
    if (init.code !== undefined) this.code = init.code;
    if (init.data !== undefined) this.data = init.data;
    if (init.extras) {
      for (const [k, v] of Object.entries(init.extras)) {
        if (!(k in this)) {
          Object.defineProperty(this, k, {
            configurable: true,
            enumerable: true,
            value: v,
          });
        }
      }
    }
  }
}

const KNOWN_ERROR_KEYS = new Set(["kind", "message", "status", "code"]);

function toCausewayError(raw: unknown): CausewayError {
  if (raw instanceof CausewayError) return raw;
  if (isRecord(raw)) {
    const r = raw;
    const kind = typeof r.kind === "string" ? r.kind : "Error";
    const message = typeof r.message === "string" ? r.message : undefined;
    const status = typeof r.status === "number" ? r.status : undefined;
    const code = typeof r.code === "string" ? r.code : undefined;
    const extras: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(r)) {
      if (!KNOWN_ERROR_KEYS.has(k)) extras[k] = v;
    }
    return new CausewayError({ kind, message, status, code, data: raw, extras });
  }
  return new CausewayError({ kind: "Error", message: String(raw), data: raw });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/**
 * Unwrap a Result envelope: returns `data` on success, throws a `CausewayError`
 * on failure. Plain (non-envelope) values pass through unchanged. Used by the
 * framework binding packages so a typed error union lands on the consumer's
 * `.error` slot rather than buried inside `.data`.
 */
type Envelope = { ok: boolean; data?: unknown; error?: unknown };
export function unwrapResult(value: unknown): unknown {
  if (value === null || typeof value !== "object") return value;
  const e = value as Envelope;
  if (typeof e.ok !== "boolean" || (!("data" in e) && !("error" in e))) return value;
  if (e.ok) return e.data;
  throw toCausewayError(e.error);
}

/** @internal — exported so generated clients can build errors with the same logic. */
export function buildError(raw: unknown): CausewayError {
  return toCausewayError(raw);
}

/** Normalize any thrown value into a `CausewayError` (bare network `TypeError`s included). */
export function normalizeError(raw: unknown): CausewayError {
  return toCausewayError(raw);
}

// `OkOf` / `ErrOf` are the distributive workers; `Ok` / `Err` apply `Awaited`
// first so users can pass a `Promise<Result<…>>` directly (which is what the
// generated `Routes.X.Return` is for unary routes). Splitting in two stages
// matters: TS only distributes a conditional over a union when the LHS is a
// *naked* type parameter, so we route `Awaited<R>` through a fresh `X` to
// force the per-branch evaluation.
type OkOf<X> = X extends { ok: true; data: infer D } ? D : never;
type ErrOf<X> = X extends { ok: false; error: infer E } ? E : never;

/** Unwrap the success type from a `Result` or `Promise<Result>`. */
export type Ok<R> = OkOf<Awaited<R>>;

/** Unwrap the error union from a `Result` or `Promise<Result>`. */
export type Err<R> = ErrOf<Awaited<R>>;
