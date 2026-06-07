// `useSubscription` — consumes a streaming route (SSE) for its lifetime,
// forwarding each event to `onEvent` and exposing connection status.

import { useEffect, useRef, useState } from "react";

import { normalizeError } from "@causewayjs/client";
import type {
  RegisteredQueryRouteKey,
  RegisteredRouteData,
  RegisteredRouteError,
  RegisteredRouteInput,
  RouteInputValue,
  UnregisteredRouteKey,
} from "@causewayjs/client";

import { useCausewayClient } from "./context.js";

export type SubscriptionStatus = "idle" | "connecting" | "open" | "closed" | "error";

export interface SubscriptionHookOptions {
  enabled?: boolean;
}

export interface SubscriptionHookResult<TError = unknown> {
  status: SubscriptionStatus;
  error: TError | null;
}

export function useSubscription<K extends RegisteredQueryRouteKey>(
  routeKey: K,
  input: RegisteredRouteInput<K>,
  onEvent: (event: RegisteredRouteData<K>) => void,
  options?: SubscriptionHookOptions,
): SubscriptionHookResult<RegisteredRouteError<K>>;
export function useSubscription<
  TEvent = unknown,
  TError = unknown,
  TInput extends RouteInputValue = RouteInputValue,
>(
  routeKey: UnregisteredRouteKey,
  input: TInput,
  onEvent: (event: TEvent) => void,
  options?: SubscriptionHookOptions,
): SubscriptionHookResult<TError>;
export function useSubscription<TEvent = unknown, TError = unknown>(
  routeKey: string,
  input: RouteInputValue,
  onEvent: (event: TEvent) => void,
  options: SubscriptionHookOptions = {},
): SubscriptionHookResult<TError> {
  const client = useCausewayClient();
  const enabled = options.enabled !== false;
  const stableKey = client.queryKey(routeKey, input);
  const [state, setState] = useState<{ status: SubscriptionStatus; error: TError | null }>({
    status: enabled ? "connecting" : "idle",
    error: null,
  });
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!enabled) {
      setState({ status: "idle", error: null });
      return;
    }
    const controller = new AbortController();
    setState({ status: "connecting", error: null });
    void (async () => {
      try {
        setState({ status: "open", error: null });
        for await (const ev of client.stream<TEvent>(routeKey, input, {
          signal: controller.signal,
        })) {
          if (controller.signal.aborted) return;
          onEventRef.current(ev);
        }
        if (controller.signal.aborted) return;
        setState({ status: "closed", error: null });
      } catch (error) {
        if (controller.signal.aborted) return;
        setState({ status: "error", error: normalizeError(error) as TError });
      }
    })();
    return () => controller.abort();
    // `input` is captured via the stable cache key; `onEvent` via a ref.
  }, [client, routeKey, stableKey, enabled]);

  return state;
}
