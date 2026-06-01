import {
  createClient,
  forwardHeaders,
  queryOptions,
  type CallOptions,
  type CausewayClient,
  type ClientConfig,
  type DehydratedClient,
  type HeaderSource,
  type QueryOptions,
  type RegisteredQueryArgs,
  type RegisteredQueryRouteKey,
  type RegisteredRouteData,
  type RegisteredRouteInput,
  type RouteInputValue,
  type UnregisteredRouteKey,
} from "@causewayjs/client";
import { createElement, type ReactElement, type ReactNode } from "react";
import type { CausewayFeedback } from "@causewayjs/react";
import type { HydrateClientProps } from "./client.js";

export interface ServerClientConfig extends Omit<ClientConfig, "headers" | "scope"> {
  headers?: HeaderSource;
  extraHeaders?: Record<string, string>;
  idempotency?: boolean;
  scope?: unknown;
}

export type ClientFactory<TClient = CausewayClient, TOptions extends object = object> = (
  options?: TOptions,
) => TClient;

type AnyClientFactory = (options?: object) => unknown;

type FactoryOptions<TFactory> = TFactory extends (options?: infer TOptions) => unknown
  ? NonNullable<TOptions> extends object
    ? NonNullable<TOptions>
    : object
  : object;

export type ServerClientOptions<TOptions extends object> = Omit<TOptions, "headers"> & {
  headers?: HeaderSource;
  extraHeaders?: Record<string, string>;
  idempotency?: boolean;
};

export type HydrateClientComponent = (props: HydrateClientProps) => ReactElement | null;

export interface ServerHydrateClientProps {
  feedback?: CausewayFeedback;
  children?: ReactNode;
}

export type ServerHydrationOptions<TOptions extends object> = ServerClientOptions<TOptions> & {
  HydrateClient?: HydrateClientComponent;
  feedback?: CausewayFeedback;
};

export type HydrationOptions<TOptions extends object> = ServerClientOptions<TOptions> & {
  prefetch?: readonly PrefetchRequest[];
};

export interface PreparedHydration<TClient = CausewayClient> {
  client: TClient;
  snapshot: DehydratedClient;
}

export function createServerClient<
  TFactory extends (options?: any) => any,
  TClient = ReturnType<TFactory>,
>(factory: TFactory, config?: ServerClientOptions<FactoryOptions<TFactory>>): TClient;
export function createServerClient(config: ServerClientConfig): CausewayClient;
export function createServerClient(
  factoryOrConfig: AnyClientFactory | ServerClientConfig,
  config?: ServerClientOptions<object>,
): unknown {
  if (typeof factoryOrConfig === "function") {
    return factoryOrConfig(normalizeServerOptions(config));
  }
  return createClient(normalizeServerOptions(factoryOrConfig) as ClientConfig);
}

type RegisteredPrefetchRequest = {
  [K in RegisteredQueryRouteKey]:
    | QueryOptions<K, RegisteredRouteInput<K>>
    | readonly [routeKey: K, ...args: RegisteredQueryArgs<K>];
}[RegisteredQueryRouteKey];

export type PrefetchRequest =
  | RegisteredPrefetchRequest
  | QueryOptions<UnregisteredRouteKey>
  | readonly [routeKey: UnregisteredRouteKey, input?: RouteInputValue, opts?: CallOptions];

type AnyPrefetchRequest =
  | QueryOptions<string, RouteInputValue>
  | readonly [routeKey: string, input?: RouteInputValue, opts?: CallOptions];

export interface Prefetcher {
  <K extends RegisteredQueryRouteKey>(
    options: QueryOptions<K, RegisteredRouteInput<K>>,
  ): Promise<RegisteredRouteData<K>>;
  <K extends RegisteredQueryRouteKey>(
    routeKey: K,
    ...args: RegisteredQueryArgs<K>
  ): Promise<RegisteredRouteData<K>>;
  <TData = unknown>(options: QueryOptions<UnregisteredRouteKey>): Promise<TData>;
  <TData = unknown>(
    routeKey: UnregisteredRouteKey,
    input?: RouteInputValue,
    opts?: CallOptions,
  ): Promise<TData>;
}

export interface ServerHydration<TClient = CausewayClient> {
  client: TClient;
  prefetch: Prefetcher;
  prefetchMany: (...requests: readonly PrefetchRequest[]) => Promise<TClient>;
  HydrateClient: (props: ServerHydrateClientProps) => ReactElement;
  hydrate: (
    children: ReactNode,
    props?: Omit<ServerHydrateClientProps, "children">,
  ) => ReactElement;
  dehydrate: () => DehydratedClient;
  snapshot: () => DehydratedClient;
}

export async function prefetch<K extends RegisteredQueryRouteKey>(
  client: unknown,
  options: QueryOptions<K, RegisteredRouteInput<K>>,
): Promise<RegisteredRouteData<K>>;
export async function prefetch<K extends RegisteredQueryRouteKey>(
  client: unknown,
  routeKey: K,
  ...args: RegisteredQueryArgs<K>
): Promise<RegisteredRouteData<K>>;
export async function prefetch<TData = unknown>(
  client: unknown,
  options: QueryOptions<UnregisteredRouteKey>,
): Promise<TData>;
export async function prefetch<TData = unknown>(
  client: unknown,
  routeKey: UnregisteredRouteKey,
  input?: RouteInputValue,
  opts?: CallOptions,
): Promise<TData>;
export async function prefetch<TData = unknown>(
  client: unknown,
  routeKeyOrOptions: string | QueryOptions,
  input?: RouteInputValue,
  opts?: CallOptions,
): Promise<TData> {
  const request = normalizePrefetchRequest(
    typeof routeKeyOrOptions === "string" ? [routeKeyOrOptions, input, opts] : routeKeyOrOptions,
  );
  return (await queryClient(client).query(request.routeKey, request.input, request.call)) as TData;
}

export async function prefetchMany<TClient>(
  client: TClient,
  ...requests: readonly PrefetchRequest[]
): Promise<TClient> {
  await Promise.all(
    requests.map((request) => {
      const { call, input, routeKey } = normalizePrefetchRequest(request);
      return queryClient(client).query(routeKey, input, call);
    }),
  );
  return client;
}

export function createServerHydration<
  TFactory extends (options?: any) => any,
  TClient = ReturnType<TFactory>,
>(
  factory: TFactory,
  config?: ServerHydrationOptions<FactoryOptions<TFactory>>,
): ServerHydration<TClient>;
export function createServerHydration(
  config: ServerHydrationOptions<ServerClientConfig>,
): ServerHydration;
export function createServerHydration(
  factoryOrConfig: AnyClientFactory | ServerHydrationOptions<ServerClientConfig>,
  config?: ServerHydrationOptions<object>,
): ServerHydration {
  const hydrationOptions = typeof factoryOrConfig === "function" ? config : factoryOrConfig;
  const {
    HydrateClient: ClientBoundary,
    clientOptions,
    feedback,
  } = splitServerHydrationOptions(hydrationOptions);
  const client =
    typeof factoryOrConfig === "function"
      ? createServerClient(factoryOrConfig as ClientFactory<CausewayClient, object>, clientOptions)
      : createServerClient(clientOptions as ServerClientConfig);
  let prefetched = false;
  let rendered = false;
  let warningScheduled = false;
  const markPrefetched = () => {
    prefetched = true;
    if (!isDevRuntime() || warningScheduled) return;
    warningScheduled = true;
    setTimeout(() => {
      if (prefetched && !rendered) {
        console.warn(
          "Causeway createServerHydration(...).prefetch() was used, but the returned <causeway.HydrateClient> boundary was not rendered. Wrap the subtree that calls useQuery() with the boundary returned from the same server hydration helper.",
        );
      }
    }, 1_000);
  };
  const markRendered = () => {
    rendered = true;
  };
  const scopedPrefetch = (async (
    routeKeyOrOptions: string | QueryOptions,
    input?: RouteInputValue,
    opts?: CallOptions,
  ) => {
    const request = normalizePrefetchRequest(
      typeof routeKeyOrOptions === "string" ? [routeKeyOrOptions, input, opts] : routeKeyOrOptions,
    );
    const data = await queryClient(client).query(request.routeKey, request.input, request.call);
    markPrefetched();
    return data;
  }) as Prefetcher;
  return {
    client,
    prefetch: scopedPrefetch,
    prefetchMany: async (...requests) => {
      const hydratedClient = await prefetchMany(client, ...requests);
      if (requests.length > 0) markPrefetched();
      return hydratedClient;
    },
    HydrateClient: (props) => {
      markRendered();
      return renderHydrateClient(asCausewayClient(client), ClientBoundary, feedback, props);
    },
    hydrate: (children, props = {}) => {
      markRendered();
      return renderHydrateClient(asCausewayClient(client), ClientBoundary, feedback, {
        ...props,
        children,
      });
    },
    dehydrate: () => dehydrate(asCausewayClient(client)),
    snapshot: () => dehydrate(asCausewayClient(client)),
  };
}

function splitServerHydrationOptions<TOptions extends object>(
  config: ServerHydrationOptions<TOptions> | undefined,
): {
  HydrateClient?: HydrateClientComponent;
  feedback?: CausewayFeedback;
  clientOptions: ServerClientOptions<TOptions> | undefined;
} {
  if (config === undefined) return { clientOptions: undefined };
  const { HydrateClient, feedback, ...clientOptions } = config;
  return {
    HydrateClient,
    feedback,
    clientOptions: clientOptions as ServerClientOptions<TOptions>,
  };
}

function renderHydrateClient(
  client: CausewayClient,
  Boundary: HydrateClientComponent | undefined,
  defaultFeedback: CausewayFeedback | undefined,
  props: ServerHydrateClientProps,
): ReactElement {
  if (Boundary === undefined) {
    throw new Error(
      "createServerHydration needs a HydrateClient component. Pass { HydrateClient } from createHydrateClient(...).",
    );
  }
  return createElement(Boundary, {
    children: props.children,
    feedback: props.feedback ?? defaultFeedback,
    state: dehydrate(client),
  });
}

export function dehydrate(client: CausewayClient): DehydratedClient {
  return client.dehydrate();
}

export function hydrate<TFactory extends (options?: any) => any, TClient = ReturnType<TFactory>>(
  factory: TFactory,
  snapshot: DehydratedClient | null | undefined,
  options?: FactoryOptions<TFactory>,
): TClient;
export function hydrate<TClient>(
  client: TClient,
  snapshot: DehydratedClient | null | undefined,
): TClient;
export function hydrate(
  clientOrFactory: unknown | AnyClientFactory,
  snapshot: DehydratedClient | null | undefined,
  options?: object,
): unknown {
  const client = typeof clientOrFactory === "function" ? clientOrFactory(options) : clientOrFactory;
  if (snapshot != null) asCausewayClient(client).hydrate(snapshot);
  return client;
}

export async function prepareHydration<
  TFactory extends (options?: any) => any,
  TClient = ReturnType<TFactory>,
>(
  factory: TFactory,
  options?: HydrationOptions<FactoryOptions<TFactory>>,
): Promise<PreparedHydration<TClient>>;
export async function prepareHydration(
  options: HydrationOptions<ServerClientConfig>,
): Promise<PreparedHydration>;
export async function prepareHydration(
  factoryOrOptions: AnyClientFactory | HydrationOptions<ServerClientConfig>,
  options?: HydrationOptions<object>,
): Promise<PreparedHydration> {
  const { prefetch: requests = [], ...clientOptions } =
    typeof factoryOrOptions === "function" ? (options ?? {}) : factoryOrOptions;
  const client =
    typeof factoryOrOptions === "function"
      ? createServerClient(factoryOrOptions as ClientFactory<CausewayClient, object>, clientOptions)
      : createServerClient(clientOptions as ServerClientConfig);
  await prefetchMany(client, ...requests);
  return { client, snapshot: dehydrate(asCausewayClient(client)) };
}

function normalizeServerOptions<TOptions extends object>(
  config: ServerClientOptions<TOptions> | ServerClientConfig | undefined,
): Omit<TOptions, "headers"> & { fetch: typeof globalThis.fetch; headers: Record<string, string> } {
  const source = (config ?? {}) as ServerClientOptions<TOptions> &
    ServerClientConfig & { fetch?: typeof globalThis.fetch };
  const { fetch: fetchImpl, headers, extraHeaders, idempotency = true, ...rest } = source;
  return {
    ...rest,
    fetch: withIdempotency(fetchImpl ?? fetch, idempotency),
    headers: { ...forwardHeaders(headers), ...extraHeaders },
  } as Omit<TOptions, "headers"> & {
    fetch: typeof globalThis.fetch;
    headers: Record<string, string>;
  };
}

export function idempotencyHeaders(key: string = crypto.randomUUID()): Record<string, string> {
  return { "idempotency-key": key };
}

function normalizePrefetchRequest(
  request: AnyPrefetchRequest,
): QueryOptions<string, RouteInputValue> {
  if (Array.isArray(request)) {
    return { routeKey: request[0], input: request[1], call: request[2] };
  }
  return request as QueryOptions<string, RouteInputValue>;
}

function asCausewayClient(client: unknown): CausewayClient {
  return client as unknown as CausewayClient;
}

function queryClient(client: unknown): CausewayClient {
  return client as unknown as CausewayClient;
}

function withIdempotency(
  fetchImpl: typeof globalThis.fetch,
  enabled: boolean,
): typeof globalThis.fetch {
  if (!enabled) return fetchImpl;
  return (input, init) => {
    const method = (init?.method ?? "GET").toUpperCase();
    if (!WRITE_METHODS.has(method)) return fetchImpl(input, init);
    const headers = new Headers(init?.headers);
    if (!headers.has("Idempotency-Key")) headers.set("Idempotency-Key", crypto.randomUUID());
    return fetchImpl(input, { ...init, headers });
  };
}

const WRITE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function isDevRuntime(): boolean {
  const env = (globalThis as { process?: { env?: { NODE_ENV?: string } } }).process?.env?.NODE_ENV;
  return env !== "production";
}

export { queryOptions };

export type {
  CallOptions,
  CausewayClient,
  ClientConfig,
  DehydratedClient,
  HeaderSource,
} from "@causewayjs/client";
