import { readable, writable } from "svelte/store";
import type { Readable, Writable } from "svelte/store";

import { normalizeError } from "@causewayjs/client";
import type {
  CallOptions,
  CausewayClient,
  RegisteredMutationRouteKey,
  RegisteredQueryRouteKey,
  RegisteredRouteData,
  RegisteredRouteError,
  RegisteredRouteInput,
  RouteInputValue,
  UnregisteredRouteKey,
} from "@causewayjs/client";

export interface QueryStoreOptions {
  enabled?: boolean;
}

export interface QueryStoreValue<TData, TError> {
  data: TData | undefined;
  error: TError | undefined;
  pending: boolean;
  refresh: (opts?: CallOptions) => void;
  setData: (value: TData | ((prev: TData | undefined) => TData)) => void;
}

export interface MutationStoreValue<TData, TError, TVars extends RouteInputValue> {
  data: TData | undefined;
  error: TError | undefined;
  pending: boolean;
  mutate: (vars: TVars, opts?: CallOptions) => Promise<TData>;
  reset: () => void;
}

export interface SubscriptionStoreValue<TError> {
  status: "idle" | "connecting" | "open" | "closed" | "error";
  error: TError | undefined;
}

export interface CausewayStores {
  query: {
    <K extends RegisteredQueryRouteKey>(
      routeKey: K,
      ...args: QueryStoreArgs<K>
    ): Readable<QueryStoreValue<RegisteredRouteData<K>, RegisteredRouteError<K>>>;
    <TData = unknown, TError = unknown, TInput extends RouteInputValue = RouteInputValue>(
      routeKey: UnregisteredRouteKey,
      input?: TInput,
      options?: QueryStoreOptions,
    ): Readable<QueryStoreValue<TData, TError>>;
  };

  mutation: {
    <K extends RegisteredMutationRouteKey>(
      routeKey: K,
    ): Readable<
      MutationStoreValue<RegisteredRouteData<K>, RegisteredRouteError<K>, RegisteredRouteInput<K>>
    >;
    <TVars extends RouteInputValue = Record<string, unknown>, TData = unknown, TError = unknown>(
      routeKey: UnregisteredRouteKey,
    ): Readable<MutationStoreValue<TData, TError, TVars>>;
  };

  subscription: {
    <K extends RegisteredQueryRouteKey>(
      routeKey: K,
      input: RegisteredRouteInput<K>,
      onEvent: (event: RegisteredRouteData<K>) => void,
      options?: { enabled?: boolean },
    ): Readable<SubscriptionStoreValue<RegisteredRouteError<K>>>;
    <TEvent = unknown, TError = unknown, TInput extends RouteInputValue = RouteInputValue>(
      routeKey: UnregisteredRouteKey,
      input: TInput,
      onEvent: (event: TEvent) => void,
      options?: { enabled?: boolean },
    ): Readable<SubscriptionStoreValue<TError>>;
  };
}

type QueryStoreArgs<K extends string> = [RegisteredRouteInput<K>] extends [void]
  ? [input?: void, options?: QueryStoreOptions]
  : [input: RegisteredRouteInput<K>, options?: QueryStoreOptions];

export function createCausewayStores(client: CausewayClient): CausewayStores {
  function query<K extends RegisteredQueryRouteKey>(
    routeKey: K,
    ...args: QueryStoreArgs<K>
  ): Readable<QueryStoreValue<RegisteredRouteData<K>, RegisteredRouteError<K>>>;
  function query<
    TData = unknown,
    TError = unknown,
    TInput extends RouteInputValue = RouteInputValue,
  >(
    routeKey: UnregisteredRouteKey,
    input?: TInput,
    options?: QueryStoreOptions,
  ): Readable<QueryStoreValue<TData, TError>>;
  function query<
    TData = unknown,
    TError = unknown,
    TInput extends RouteInputValue = RouteInputValue,
  >(routeKey: string, input?: TInput, options: QueryStoreOptions = {}) {
    const enabled = options.enabled ?? true;
    type V = QueryStoreValue<TData, TError>;
    let controller: AbortController | null = null;
    const inner: Writable<V> = writable({
      data: undefined,
      error: undefined,
      pending: enabled,
      refresh: (opts?: CallOptions) => run(opts),
      setData: (value) =>
        inner.update((s) => ({
          ...s,
          data:
            typeof value === "function"
              ? (value as (p: TData | undefined) => TData)(s.data)
              : value,
        })),
    });

    function run(opts: CallOptions = {}) {
      controller?.abort();
      controller = new AbortController();
      inner.update((s) => ({ ...s, error: undefined, pending: true }));
      void (async () => {
        try {
          const data = await client.query<TData>(routeKey, toInput(input), {
            ...opts,
            signal: opts.signal ?? controller?.signal,
          });
          inner.update((s) => ({ ...s, data, error: undefined, pending: false }));
        } catch (error) {
          if (isAbortError(error)) return;
          inner.update((s) => ({
            ...s,
            error: normalizeError(error) as TError,
            pending: false,
          }));
        }
      })();
    }

    if (enabled) run();
    return { subscribe: inner.subscribe };
  }

  function mutation<K extends RegisteredMutationRouteKey>(
    routeKey: K,
  ): Readable<
    MutationStoreValue<RegisteredRouteData<K>, RegisteredRouteError<K>, RegisteredRouteInput<K>>
  >;
  function mutation<
    TVars extends RouteInputValue = Record<string, unknown>,
    TData = unknown,
    TError = unknown,
  >(routeKey: UnregisteredRouteKey): Readable<MutationStoreValue<TData, TError, TVars>>;
  function mutation<
    TVars extends RouteInputValue = Record<string, unknown>,
    TData = unknown,
    TError = unknown,
  >(routeKey: string) {
    type V = MutationStoreValue<TData, TError, TVars>;
    const inner: Writable<V> = writable({
      data: undefined,
      error: undefined,
      pending: false,
      mutate: async (vars: TVars, opts: CallOptions = {}) => {
        inner.update((s) => ({ ...s, error: undefined, pending: true }));
        try {
          const data = await client.mutate<TData>(routeKey, toInput(vars), opts);
          inner.update((s) => ({ ...s, data, pending: false }));
          return data;
        } catch (error) {
          const typed = normalizeError(error) as TError;
          inner.update((s) => ({ ...s, error: typed, pending: false }));
          throw typed;
        }
      },
      reset: () =>
        inner.set({
          data: undefined,
          error: undefined,
          pending: false,
          mutate: getStore().mutate,
          reset: getStore().reset,
        }),
    });
    let captured: V;
    inner.subscribe((v) => (captured = v));
    function getStore(): V {
      return captured;
    }
    return { subscribe: inner.subscribe };
  }

  function subscription<K extends RegisteredQueryRouteKey>(
    routeKey: K,
    input: RegisteredRouteInput<K>,
    onEvent: (event: RegisteredRouteData<K>) => void,
    options?: { enabled?: boolean },
  ): Readable<SubscriptionStoreValue<RegisteredRouteError<K>>>;
  function subscription<
    TEvent = unknown,
    TError = unknown,
    TInput extends RouteInputValue = RouteInputValue,
  >(
    routeKey: UnregisteredRouteKey,
    input: TInput,
    onEvent: (event: TEvent) => void,
    options?: { enabled?: boolean },
  ): Readable<SubscriptionStoreValue<TError>>;
  function subscription<
    TEvent = unknown,
    TError = unknown,
    TInput extends RouteInputValue = RouteInputValue,
  >(
    routeKey: string,
    input: TInput,
    onEvent: (event: TEvent) => void,
    options: { enabled?: boolean } = {},
  ) {
    const enabled = options.enabled ?? true;
    return readable<SubscriptionStoreValue<TError>>(
      { error: undefined, status: enabled ? "connecting" : "idle" },
      (set) => {
        if (!enabled) return;
        const controller = new AbortController();
        set({ error: undefined, status: "connecting" });
        void (async () => {
          try {
            set({ error: undefined, status: "open" });
            for await (const ev of client.stream<TEvent>(routeKey, toInput(input), {
              signal: controller.signal,
            })) {
              if (controller.signal.aborted) return;
              onEvent(ev);
            }
            if (controller.signal.aborted) return;
            set({ error: undefined, status: "closed" });
          } catch (error) {
            if (controller.signal.aborted) return;
            set({ error: normalizeError(error) as TError, status: "error" });
          }
        })();
        return () => controller.abort();
      },
    );
  }

  return { mutation, query, subscription };
}

function toInput(input: RouteInputValue): Record<string, unknown> | void {
  return input;
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}
