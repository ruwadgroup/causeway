import { createEffect, createResource, createSignal, onCleanup } from "solid-js";
import type { Accessor } from "solid-js";

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

type InputSource<TInput extends RouteInputValue> = TInput | Accessor<TInput>;
type QuerySource<TInput extends RouteInputValue> = { input: TInput };

export interface QueryResource<TData, TError> {
  data: Accessor<TData | undefined>;
  error: Accessor<TError | undefined>;
  pending: Accessor<boolean>;
  refresh: () => Promise<TData | undefined>;
  setData: (value: TData | ((prev: TData | undefined) => TData)) => void;
}

export interface MutationResource<TData, TError, TVars extends RouteInputValue> {
  data: Accessor<TData | undefined>;
  error: Accessor<TError | undefined>;
  pending: Accessor<boolean>;
  mutate: (vars: TVars, opts?: CallOptions) => Promise<TData>;
  reset: () => void;
}

export interface SubscriptionResource<TError> {
  status: Accessor<"idle" | "connecting" | "open" | "closed" | "error">;
  error: Accessor<TError | undefined>;
}

export interface CausewayResources {
  query: {
    <K extends RegisteredQueryRouteKey>(
      routeKey: K,
      input?: InputSource<RegisteredRouteInput<K>>,
    ): QueryResource<RegisteredRouteData<K>, RegisteredRouteError<K>>;
    <TData = unknown, TError = unknown, TInput extends RouteInputValue = RouteInputValue>(
      routeKey: UnregisteredRouteKey,
      input?: InputSource<TInput>,
    ): QueryResource<TData, TError>;
  };

  mutation: {
    <K extends RegisteredMutationRouteKey>(
      routeKey: K,
    ): MutationResource<RegisteredRouteData<K>, RegisteredRouteError<K>, RegisteredRouteInput<K>>;
    <TVars extends RouteInputValue = Record<string, unknown>, TData = unknown, TError = unknown>(
      routeKey: UnregisteredRouteKey,
    ): MutationResource<TData, TError, TVars>;
  };

  subscription: {
    <K extends RegisteredQueryRouteKey>(
      routeKey: K,
      input: InputSource<RegisteredRouteInput<K>>,
      onEvent: (event: RegisteredRouteData<K>) => void,
    ): SubscriptionResource<RegisteredRouteError<K>>;
    <TEvent = unknown, TError = unknown, TInput extends RouteInputValue = RouteInputValue>(
      routeKey: UnregisteredRouteKey,
      input: InputSource<TInput>,
      onEvent: (event: TEvent) => void,
    ): SubscriptionResource<TError>;
  };
}

export function createCausewayResources(client: CausewayClient): CausewayResources {
  function query<K extends RegisteredQueryRouteKey>(
    routeKey: K,
    input?: InputSource<RegisteredRouteInput<K>>,
  ): QueryResource<RegisteredRouteData<K>, RegisteredRouteError<K>>;
  function query<
    TData = unknown,
    TError = unknown,
    TInput extends RouteInputValue = RouteInputValue,
  >(routeKey: UnregisteredRouteKey, input?: InputSource<TInput>): QueryResource<TData, TError>;
  function query<
    TData = unknown,
    TError = unknown,
    TInput extends RouteInputValue = RouteInputValue,
  >(routeKey: string, input?: InputSource<TInput>) {
    const [errorSignal, setError] = createSignal<TError | undefined>(undefined);
    const [data, { mutate, refetch }] = createResource<TData, QuerySource<TInput>>(
      () => ({ input: readInput(input) }),
      async ({ input: vars }) => {
        try {
          const result = await client.query<TData>(routeKey, toInput(vars));
          setError(() => undefined);
          return result;
        } catch (error) {
          setError(() => normalizeError(error) as TError);
          throw error;
        }
      },
    );
    return {
      data: () => data(),
      error: errorSignal,
      pending: () => data.loading,
      refresh: () => Promise.resolve(refetch()),
      setData: (value) => {
        mutate(value as Parameters<typeof mutate>[0]);
      },
    } as QueryResource<TData, TError>;
  }

  function mutation<K extends RegisteredMutationRouteKey>(
    routeKey: K,
  ): MutationResource<RegisteredRouteData<K>, RegisteredRouteError<K>, RegisteredRouteInput<K>>;
  function mutation<
    TVars extends RouteInputValue = Record<string, unknown>,
    TData = unknown,
    TError = unknown,
  >(routeKey: UnregisteredRouteKey): MutationResource<TData, TError, TVars>;
  function mutation<
    TVars extends RouteInputValue = Record<string, unknown>,
    TData = unknown,
    TError = unknown,
  >(routeKey: string) {
    const [data, setData] = createSignal<TData | undefined>(undefined);
    const [errorSignal, setError] = createSignal<TError | undefined>(undefined);
    const [pending, setPending] = createSignal(false);

    async function mutate(vars: TVars, opts: CallOptions = {}): Promise<TData> {
      setPending(true);
      setError(() => undefined);
      try {
        const result = await client.mutate<TData>(routeKey, toInput(vars), opts);
        setData(() => result);
        return result;
      } catch (error) {
        const typed = normalizeError(error) as TError;
        setError(() => typed);
        throw typed;
      } finally {
        setPending(false);
      }
    }

    function reset() {
      setData(() => undefined);
      setError(() => undefined);
      setPending(false);
    }

    return { data, error: errorSignal, pending, mutate, reset };
  }

  function subscription<K extends RegisteredQueryRouteKey>(
    routeKey: K,
    input: InputSource<RegisteredRouteInput<K>>,
    onEvent: (event: RegisteredRouteData<K>) => void,
  ): SubscriptionResource<RegisteredRouteError<K>>;
  function subscription<
    TEvent = unknown,
    TError = unknown,
    TInput extends RouteInputValue = RouteInputValue,
  >(
    routeKey: UnregisteredRouteKey,
    input: InputSource<TInput>,
    onEvent: (event: TEvent) => void,
  ): SubscriptionResource<TError>;
  function subscription<
    TEvent = unknown,
    TError = unknown,
    TInput extends RouteInputValue = RouteInputValue,
  >(routeKey: string, input: InputSource<TInput>, onEvent: (event: TEvent) => void) {
    const [status, setStatus] = createSignal<"idle" | "connecting" | "open" | "closed" | "error">(
      "idle",
    );
    const [errorSignal, setError] = createSignal<TError | undefined>(undefined);

    createEffect(() => {
      const vars = readInput(input);
      const controller = new AbortController();
      setStatus("connecting");
      setError(() => undefined);

      void (async () => {
        try {
          setStatus("open");
          for await (const ev of client.stream<TEvent>(routeKey, toInput(vars), {
            signal: controller.signal,
          })) {
            if (controller.signal.aborted) return;
            onEvent(ev);
          }
          if (controller.signal.aborted) return;
          setStatus("closed");
        } catch (error) {
          if (controller.signal.aborted) return;
          setError(() => normalizeError(error) as TError);
          setStatus("error");
        }
      })();

      onCleanup(() => controller.abort());
    });

    return { error: errorSignal, status };
  }

  return { mutation, query, subscription };
}

function readInput<TInput extends RouteInputValue>(input: InputSource<TInput> | undefined): TInput {
  return typeof input === "function" ? (input as Accessor<TInput>)() : (input as TInput);
}

function toInput(input: RouteInputValue): Record<string, unknown> | void {
  return input;
}
