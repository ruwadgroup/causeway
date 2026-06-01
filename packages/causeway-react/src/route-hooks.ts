import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import type { ReactElement, ReactNode } from "react";

import type {
  CallOptions,
  CausewayClient,
  DehydratedClient,
  QueryOptions,
  QueryState,
  RegisteredMutationRouteKey,
  RegisteredQueryRouteKey,
  RegisteredRouteData,
  RegisteredRouteError,
  RegisteredRouteInput,
  RouteInputValue,
  UnregisteredRouteKey,
} from "@causewayjs/client";

export interface CausewayFeedback {
  loading?: (message: string, id: string) => unknown;
  success?: (message: string, id: string) => unknown;
  error?: (message: string, id: string) => unknown;
}

interface ProviderValue {
  client: CausewayClient;
  feedback?: CausewayFeedback;
}

export interface CausewayProviderProps {
  client: CausewayClient;
  feedback?: CausewayFeedback;
  children?: ReactNode;
}

export interface QueryHookOptions {
  enabled?: boolean;
  keepPreviousData?: boolean;
  refetchOnMount?: boolean | "stale";
  staleTime?: number;
}

export interface QueryHookResult<TData = unknown, TError = unknown> {
  data: TData | undefined;
  pending: boolean;
  error: TError | null;
  refresh: (opts?: CallOptions) => Promise<TData>;
  setData: (next: TData | ((current: TData | undefined) => TData)) => void;
}

type QueryHookArgs<K extends string> = [RegisteredRouteInput<K>] extends [void]
  ? [input?: void, options?: QueryHookOptions]
  : [input: RegisteredRouteInput<K>, options?: QueryHookOptions];

export interface MutationFeedback<TError = unknown> {
  loading?: string;
  success?: string;
  error?: string | ((error: TError) => string);
}

export interface MutationHookOptions<TError = unknown> {
  feedback?: MutationFeedback<TError>;
}

export type MutationHookResult<
  TVars extends RouteInputValue = Record<string, unknown>,
  TData = unknown,
  TError = unknown,
> = ((vars: TVars, opts?: CallOptions) => Promise<TData>) & {
  pending: boolean;
  error: TError | null;
  data: TData | undefined;
  reset: () => void;
};

const CausewayContext = createContext<ProviderValue | null>(null);

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

const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

export function CausewayProvider({
  client,
  feedback,
  children,
}: CausewayProviderProps): ReactElement {
  const value = useMemo(() => ({ client, feedback }), [client, feedback]);
  return createElement(CausewayContext.Provider, { value }, children);
}

export function useCausewayClient(): CausewayClient {
  const value = useContext(CausewayContext);
  if (value === null) throw new Error("useCausewayClient must be used inside <CausewayProvider>");
  return value.client;
}

export function useOptionalCausewayClient(): CausewayClient | null {
  return useContext(CausewayContext)?.client ?? null;
}

export function useQuery<K extends RegisteredQueryRouteKey>(
  options: QueryOptions<K, RegisteredRouteInput<K>>,
  hookOptions?: QueryHookOptions,
): QueryHookResult<RegisteredRouteData<K>, RegisteredRouteError<K>>;
export function useQuery<TData = unknown, TError = unknown>(
  options: QueryOptions<UnregisteredRouteKey>,
  hookOptions?: QueryHookOptions,
): QueryHookResult<TData, TError>;
export function useQuery<K extends RegisteredQueryRouteKey>(
  routeKey: K,
  ...args: QueryHookArgs<K>
): QueryHookResult<RegisteredRouteData<K>, RegisteredRouteError<K>>;
export function useQuery<TData = unknown, TError = unknown>(
  routeKey: UnregisteredRouteKey,
  input?: RouteInputValue,
  options?: QueryHookOptions,
): QueryHookResult<TData, TError>;
export function useQuery<TData = unknown, TError = unknown>(
  routeKeyOrOptions: string | QueryOptions,
  inputOrOptions?: RouteInputValue | QueryHookOptions,
  maybeOptions: QueryHookOptions = {},
): QueryHookResult<TData, TError> {
  const client = useCausewayClient();
  const query = toQueryParts(routeKeyOrOptions, inputOrOptions, maybeOptions);
  const { call, input, options, routeKey } = query;
  const stableKey = client.queryKey(routeKey, input);

  const subscribe = useCallback(
    (notify: () => void) => client.subscribe(routeKey, input, notify),
    [client, routeKey, stableKey],
  );
  const getSnapshot = useCallback(
    () => client.getQueryState<TData, TError>(routeKey, input),
    [client, routeKey, stableKey],
  );
  const state = useSyncExternalStore<QueryState<TData, TError>>(
    subscribe,
    getSnapshot,
    getSnapshot,
  );
  const mountedKeys = useRef(new Set<string>());
  const hideDataKeys = useRef(new Set<string>());
  const shouldRefreshOnMount =
    options.enabled !== false &&
    !mountedKeys.current.has(stableKey) &&
    (options.refetchOnMount === undefined ||
      options.refetchOnMount === true ||
      (options.refetchOnMount === "stale" && isStale(state.updatedAt, options.staleTime)) ||
      state.data === undefined);
  const hideStaleData =
    options.keepPreviousData !== true &&
    state.error === null &&
    (shouldRefreshOnMount || (state.pending && hideDataKeys.current.has(stableKey)));
  const data = hideStaleData ? undefined : state.data;
  const pending = state.pending || (shouldRefreshOnMount && state.error === null);

  useIsomorphicLayoutEffect(() => {
    if (options.enabled === false) return;
    const controller = new AbortController();
    const current = client.getQueryState<TData, TError>(routeKey, input);
    const shouldRefresh =
      options.refetchOnMount === false
        ? current.data === undefined
        : options.refetchOnMount === "stale"
          ? isStale(current.updatedAt, options.staleTime)
          : true;
    const request = shouldRefresh ? client.refresh : client.query;
    const requestOptions: CallOptions = {
      ...call,
      signal: controller.signal,
      ...(shouldRefresh && options.keepPreviousData !== true ? { cache: "no-store" } : {}),
    };
    if (shouldRefresh && options.keepPreviousData !== true) hideDataKeys.current.add(stableKey);
    void request
      .call(client, routeKey, input, requestOptions)
      .finally(() => hideDataKeys.current.delete(stableKey))
      .catch(() => {});
    mountedKeys.current.add(stableKey);
    return () => controller.abort();
  }, [
    client,
    routeKey,
    stableKey,
    options.enabled,
    options.keepPreviousData,
    options.refetchOnMount,
    options.staleTime,
  ]);

  useEffect(() => {
    warnOnHydrationKeyMismatch(client, routeKey, input, stableKey, state.data);
  }, [client, routeKey, stableKey, state.data]);

  const refresh = useCallback(
    (opts: CallOptions = {}) => client.refresh<TData>(routeKey, input, { ...call, ...opts }),
    [client, routeKey, stableKey],
  );
  const setData = useCallback(
    (next: TData | ((current: TData | undefined) => TData)) => {
      const current = client.getData<TData>(routeKey, input);
      const value =
        typeof next === "function" ? (next as (v: TData | undefined) => TData)(current) : next;
      client.setData(routeKey, input, value);
    },
    [client, routeKey, stableKey],
  );

  return {
    data,
    pending,
    error: state.error,
    refresh,
    setData,
  };
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
      input: query.input as RouteInputValue,
      key: client.queryKey(query.routeKey, query.input as Record<string, unknown> | void),
    })),
  ];
}

function warnOnHydrationKeyMismatch(
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

function isBrowserRuntime(): boolean {
  return typeof window !== "undefined";
}

function isDevRuntime(): boolean {
  const env = (globalThis as { process?: { env?: { NODE_ENV?: string } } }).process?.env?.NODE_ENV;
  return env !== "production";
}

function isStale(updatedAt: number | undefined, staleTime: number = 0): boolean {
  return updatedAt === undefined || Date.now() - updatedAt >= staleTime;
}

function formatDevValue(value: unknown): string {
  if (value === undefined) return "undefined";
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function isQueryOptions(value: unknown): value is QueryOptions {
  return typeof value === "object" && value !== null && "routeKey" in value;
}

function toQueryParts(
  routeKeyOrOptions: string | QueryOptions,
  inputOrOptions: RouteInputValue | QueryHookOptions | undefined,
  maybeOptions: QueryHookOptions,
): {
  routeKey: string;
  input: RouteInputValue;
  call?: CallOptions;
  options: QueryHookOptions;
} {
  if (isQueryOptions(routeKeyOrOptions)) {
    return {
      routeKey: routeKeyOrOptions.routeKey,
      input: routeKeyOrOptions.input,
      call: routeKeyOrOptions.call,
      options: (inputOrOptions as QueryHookOptions | undefined) ?? {},
    };
  }
  return {
    routeKey: routeKeyOrOptions,
    input: inputOrOptions as RouteInputValue,
    options: maybeOptions,
  };
}

export function useMutation<K extends RegisteredMutationRouteKey>(
  routeKey: K,
  options?: MutationHookOptions<RegisteredRouteError<K>>,
): MutationHookResult<RegisteredRouteInput<K>, RegisteredRouteData<K>, RegisteredRouteError<K>>;
export function useMutation<
  TVars extends RouteInputValue = Record<string, unknown>,
  TData = unknown,
  TError = unknown,
>(
  routeKey: UnregisteredRouteKey,
  options?: MutationHookOptions<TError>,
): MutationHookResult<TVars, TData, TError>;
export function useMutation<
  TVars extends RouteInputValue = Record<string, unknown>,
  TData = unknown,
  TError = unknown,
>(
  routeKey: string,
  options: MutationHookOptions<TError> = {},
): MutationHookResult<TVars, TData, TError> {
  const value = useContext(CausewayContext);
  if (value === null) throw new Error("useMutation must be used inside <CausewayProvider>");
  const [state, setState] = useState<{
    pending: boolean;
    error: TError | null;
    data: TData | undefined;
  }>({ pending: false, error: null, data: undefined });
  const feedbackId = useRef(`causeway:${routeKey}`);

  const run = useCallback(
    async (vars: TVars, opts: CallOptions = {}) => {
      setState((current) => ({ ...current, pending: true, error: null }));
      if (options.feedback?.loading) {
        value.feedback?.loading?.(options.feedback.loading, feedbackId.current);
      }
      try {
        const data = await value.client.mutate<TData>(routeKey, vars, opts);
        setState({ pending: false, error: null, data });
        if (options.feedback?.success) {
          value.feedback?.success?.(options.feedback.success, feedbackId.current);
        }
        return data;
      } catch (error) {
        const typed = error as TError;
        setState((current) => ({ ...current, pending: false, error: typed }));
        const message =
          typeof options.feedback?.error === "function"
            ? options.feedback.error(typed)
            : options.feedback?.error;
        if (message) value.feedback?.error?.(message, feedbackId.current);
        throw error;
      }
    },
    [value, routeKey, options.feedback],
  );

  const reset = useCallback(() => {
    setState({ pending: false, error: null, data: undefined });
  }, []);

  return Object.assign(run, {
    pending: state.pending,
    error: state.error,
    data: state.data,
    reset,
  });
}
