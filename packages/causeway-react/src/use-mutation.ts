// `useMutation` — runs a route-key mutation, tracks pending/error/data, and
// fires optional provider feedback (toast-style loading/success/error hooks).
// The returned value is callable *and* carries the state fields.

import { useCallback, useContext, useRef, useState } from "react";

import { normalizeError } from "@causewayjs/client";
import type {
  CallOptions,
  RegisteredMutationRouteKey,
  RegisteredRouteData,
  RegisteredRouteError,
  RegisteredRouteInput,
  RouteInputValue,
  UnregisteredRouteKey,
} from "@causewayjs/client";

import { CausewayContext } from "./context.js";

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
  mutate: (vars: TVars, opts?: CallOptions) => Promise<TData>;
  pending: boolean;
  error: TError | null;
  data: TData | undefined;
  reset: () => void;
};

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
        const typed = normalizeError(error) as TError;
        setState((current) => ({ ...current, pending: false, error: typed }));
        const message =
          typeof options.feedback?.error === "function"
            ? options.feedback.error(typed)
            : options.feedback?.error;
        if (message) value.feedback?.error?.(message, feedbackId.current);
        throw typed;
      }
    },
    [value, routeKey, options.feedback],
  );

  const reset = useCallback(() => {
    setState({ pending: false, error: null, data: undefined });
  }, []);

  return Object.assign(run, {
    mutate: run,
    pending: state.pending,
    error: state.error,
    data: state.data,
    reset,
  });
}
