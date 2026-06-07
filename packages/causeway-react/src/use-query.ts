import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";

import type {
  CallOptions,
  QueryOptions,
  QueryState,
  RegisteredQueryRouteKey,
  RegisteredRouteData,
  RegisteredRouteError,
  RegisteredRouteInput,
  RouteInputValue,
  UnregisteredRouteKey,
} from "@causewayjs/client";

import { useCausewayClient } from "./context.js";
import { warnOnHydrationKeyMismatch } from "./hydration.js";
import { useIsomorphicLayoutEffect } from "./runtime-env.js";

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
  const { call, input, options, routeKey } = toQueryParts(
    routeKeyOrOptions,
    inputOrOptions,
    maybeOptions,
  );
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
  const mountedKeyRef = useRef<string | null>(null);
  const hideDataKeyRef = useRef<string | null>(null);
  const shouldRefreshOnMount =
    options.enabled !== false &&
    mountedKeyRef.current !== stableKey &&
    (options.refetchOnMount === undefined ||
      options.refetchOnMount === true ||
      (options.refetchOnMount === "stale" && isStale(state.updatedAt, options.staleTime)) ||
      state.data === undefined);
  const hideStaleData =
    options.keepPreviousData !== true &&
    state.data === undefined &&
    state.error === null &&
    (shouldRefreshOnMount || (state.pending && hideDataKeyRef.current === stableKey));
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
    if (shouldRefresh && options.keepPreviousData !== true) hideDataKeyRef.current = stableKey;
    void request
      .call(client, routeKey, input, requestOptions)
      .finally(() => {
        if (hideDataKeyRef.current === stableKey) hideDataKeyRef.current = null;
      })
      .catch(() => {});
    mountedKeyRef.current = stableKey;
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

  return { data, pending, error: state.error, refresh, setData };
}

function isStale(updatedAt: number | undefined, staleTime: number = 0): boolean {
  return updatedAt === undefined || Date.now() - updatedAt >= staleTime;
}

function isQueryOptions(value: unknown): value is QueryOptions {
  return typeof value === "object" && value !== null && "routeKey" in value;
}

function isRouteInputValue(value: unknown): value is RouteInputValue {
  return value === undefined || (typeof value === "object" && value !== null);
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
  if (!isRouteInputValue(inputOrOptions)) {
    throw new TypeError("Causeway query input must be an object or undefined.");
  }
  return {
    routeKey: routeKeyOrOptions,
    input: inputOrOptions,
    options: maybeOptions,
  };
}
