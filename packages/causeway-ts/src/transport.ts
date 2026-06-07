import { parseSSE } from "./sse.js";
import { buildError, CausewayError } from "./types.js";
import type { CallOptions, Result, RouteDescriptor } from "./types.js";
import { camelToSnakeDeepGuarded, snakeToCamelDeepGuarded } from "./case.js";
import { isPlainObject, safeJsonParse, sleep } from "./utils.js";
import type { Args, FetchImpl } from "./utils.js";

export function buildRequest(
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

  for (const param of route.params ?? []) {
    const value = args[param.name];
    if (value === undefined || (param.in === "query" && value === null)) continue;

    switch (param.in) {
      case "path":
        path = path.replace(`{${param.alias}}`, encodeURIComponent(String(value)));
        break;
      case "query":
        appendQuery(query, param.alias, value);
        break;
      case "header":
        headers[param.alias] = String(value);
        break;
      case "cookie":
        headers["cookie"] =
          `${headers["cookie"] ? `${headers["cookie"]}; ` : ""}${param.alias}=${String(value)}`;
        break;
      case "file":
        multipart ??= new FormData();
        multipart.append(param.alias, value instanceof Blob ? value : String(value));
        bodyMode = "multipart";
        break;
      case "body":
        if (route.binaryBody) {
          bodyWhole = value;
          bodyMode = "binary";
        } else if (route.formBody) {
          bodyWhole = value;
          bodyMode = "form";
        } else if (param.embed) {
          bodyEmbed[param.alias] = value;
          if (bodyMode === "none") bodyMode = "json";
        } else {
          bodyWhole = value;
          if (bodyMode === "none") bodyMode = "json";
        }
        break;
    }
  }

  const body = encodeBody(bodyMode, bodyEmbed, bodyWhole, multipart, headers, route);
  const qs = query.toString();
  const missingPathParam = path.match(/\{([^}]+)\}/);
  if (missingPathParam) {
    throw new Error(
      `Missing path parameter "${missingPathParam[1]}" for Causeway route ${route.routeKey}`,
    );
  }

  return {
    url: `${baseUrl}${path}${qs ? `?${qs}` : ""}`,
    init: { method: route.method, headers, body, signal: opts.signal },
  };
}

export async function unaryCall(
  route: RouteDescriptor,
  url: string,
  init: RequestInit,
  fetchImpl: FetchImpl,
): Promise<unknown> {
  const res = await fetchImpl(url, init);

  if (route.binaryResponse) {
    if (!res.ok) throw await httpError(res);
    return await res.blob();
  }

  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    const raw: unknown = await res.json();
    const value = snakeToCamelDeepGuarded(raw, route.opaqueResponsePaths);
    if (isTypedErrorEnvelope(value)) {
      if (route.result) return value as Result<unknown, unknown>;
      const errPayload = value.error;
      throw buildError({ ...errPayload, status: errPayload.status ?? res.status });
    }
    if (!res.ok) throw httpErrorFromJson(res.status, raw);
    return route.result ? (value as Result<unknown, unknown>) : value;
  }

  if (!res.ok) throw await httpError(res);
  if (res.status === 204 || contentType === "") return undefined;
  return await res.text();
}

export async function* streamCall(
  route: RouteDescriptor,
  args: Args,
  opts: CallOptions,
  baseUrl: string,
  defaultHeaders: Record<string, string> | undefined,
  fetchImpl: FetchImpl,
): AsyncIterableIterator<unknown> {
  let lastId: string | undefined;
  let retryMs = 1000;
  const startedAt = Date.now();
  const maxResumeWindowMs = 5 * 60 * 1000;

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
      for await (const event of parseSSE(res.body)) {
        if (event.retry !== undefined) retryMs = Math.min(event.retry, 30_000);
        if (event.id !== undefined) lastId = event.id;
        if (event.event === "done") {
          sawDone = true;
          return;
        }
        if (event.event === "error") throw terminalStreamError(event.data);
        if (event.data === "") continue;
        yield snakeToCamelDeepGuarded(safeJsonParse(event.data), route.opaqueResponsePaths);
      }
    } catch (error) {
      if (opts.signal?.aborted) return;
      if (isTerminalStreamError(error)) throw error;
      if (Date.now() - startedAt > maxResumeWindowMs) throw error;
      await sleep(retryMs, opts.signal);
      continue;
    }

    if (sawDone || opts.signal?.aborted) return;
    if (Date.now() - startedAt > maxResumeWindowMs) return;
    await sleep(retryMs, opts.signal);
  }
}

function appendQuery(query: URLSearchParams, key: string, value: unknown): void {
  if (Array.isArray(value)) {
    for (const item of value) {
      if (item !== null && item !== undefined) query.append(key, String(item));
    }
    return;
  }
  query.append(key, String(value));
}

function encodeBody(
  mode: "none" | "json" | "multipart" | "binary" | "form",
  embedded: Record<string, unknown>,
  whole: unknown,
  multipart: FormData | null,
  headers: Record<string, string>,
  route: RouteDescriptor,
): BodyInit | undefined {
  if (mode === "json") {
    headers["content-type"] ??= "application/json";
    const payload = Object.keys(embedded).length > 0 ? embedded : whole;
    return payload === undefined
      ? undefined
      : JSON.stringify(camelToSnakeDeepGuarded(payload, route.opaqueRequestPaths));
  }
  if (mode === "multipart" && multipart !== null) {
    delete headers["content-type"];
    return multipart;
  }
  if (mode === "binary") {
    headers["content-type"] ??= "application/octet-stream";
    return whole as BodyInit;
  }
  if (mode === "form") {
    headers["content-type"] ??= "application/x-www-form-urlencoded";
    const payload = camelToSnakeDeepGuarded(whole, route.opaqueRequestPaths);
    if (!isPlainObject(payload)) throw new TypeError("Causeway form body must be an object.");
    const form = new URLSearchParams();
    for (const [key, value] of Object.entries(payload)) {
      if (value === undefined || value === null) continue;
      if (Array.isArray(value)) for (const item of value) form.append(key, String(item));
      else form.append(key, String(value));
    }
    return form.toString();
  }
  return undefined;
}

function isTypedErrorEnvelope(
  value: unknown,
): value is { ok: false; error: Record<string, unknown> & { kind: string } } {
  if (!isPlainObject(value) || value.ok !== false) return false;
  const { error } = value;
  return isPlainObject(error) && typeof error.kind === "string";
}

function httpErrorFromJson(status: number, raw: unknown): CausewayError {
  if (isPlainObject(raw)) return buildError({ ...raw, status });
  return new CausewayError({
    kind: "HttpError",
    status,
    message: `HTTP ${status}`,
    data: raw,
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

function terminalStreamError(data: string): Error {
  return Object.assign(new Error("stream error"), {
    kind: "error",
    payload: safeJsonParse(data),
    causewayTerminal: true,
  });
}

function isTerminalStreamError(error: unknown): boolean {
  return (
    (typeof error === "object" || typeof error === "function") &&
    error !== null &&
    Reflect.get(error, "causewayTerminal") === true
  );
}
