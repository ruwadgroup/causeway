import { Fragment, createElement, useLayoutEffect, useMemo, useRef } from "react";
import type { ReactNode } from "react";

import type { CausewayClient, DehydratedClient } from "@causewayjs/client";
import {
  CausewayProvider,
  registerCausewayHydrationSnapshot,
  useOptionalCausewayClient,
  type CausewayFeedback,
} from "@causewayjs/react";

export type ClientFactory<TClient = CausewayClient, TOptions extends object = object> = (
  options?: TOptions,
) => TClient;

export type HeaderRecord = Record<string, string | null | undefined>;

export type BrowserClientOptions<TOptions extends object> = Omit<TOptions, "fetch" | "headers"> & {
  baseUrl?: string;
  credentials?: RequestCredentials;
  fetch?: typeof globalThis.fetch;
  headers?: HeaderRecord | (() => HeaderRecord | null | undefined);
  idempotency?: boolean;
};

export interface HydrateClientProps {
  state?: DehydratedClient | null;
  snapshot?: DehydratedClient | null;
  feedback?: CausewayFeedback;
  children?: ReactNode;
}

export function createHydrateClient<
  TFactory extends (options?: any) => any,
  TOptions extends object = Parameters<TFactory>[0] extends object
    ? NonNullable<Parameters<TFactory>[0]>
    : object,
>(factory: TFactory, options?: TOptions) {
  return function HydrateClient({ children, feedback, snapshot, state }: HydrateClientProps) {
    const hydrationState = state ?? snapshot;
    const hydrationKey = useMemo(() => snapshotKey(hydrationState), [hydrationState]);
    const parentClient = useOptionalCausewayClient();
    const fallbackClient = useRef<unknown>(null);
    const lastHydration = useRef<{ client: CausewayClient; key: string } | null>(null);
    const lastNotification = useRef<{ client: CausewayClient; key: string } | null>(null);

    if (parentClient === null && fallbackClient.current === null) {
      fallbackClient.current = factory(options);
    }

    const client = (parentClient ?? fallbackClient.current) as CausewayClient;

    if (hydrationState != null && hydrationKey != null) {
      const last = lastHydration.current;
      if (last?.client !== client || last.key !== hydrationKey) {
        client.hydrate(hydrationState, { notify: false });
        lastHydration.current = { client, key: hydrationKey };
      }
    }

    useLayoutEffect(() => {
      if (hydrationState == null || hydrationKey == null) return;
      const last = lastNotification.current;
      if (last?.client === client && last.key === hydrationKey) return;
      client.hydrate(hydrationState, { forceNotify: true });
      registerCausewayHydrationSnapshot(client, hydrationState);
      lastNotification.current = { client, key: hydrationKey };
    }, [client, hydrationKey, hydrationState]);

    if (parentClient !== null && feedback === undefined) {
      return createElement(Fragment, null, children);
    }
    return createElement(CausewayProvider, { client, feedback }, children);
  };
}

export function createBrowserClient<TFactory extends (options?: any) => any>(
  factory: TFactory,
  options?: BrowserClientOptions<
    Parameters<TFactory>[0] extends object ? NonNullable<Parameters<TFactory>[0]> : object
  >,
): ReturnType<TFactory> {
  const {
    credentials = "include",
    fetch: fetchImpl = fetch,
    headers,
    idempotency = true,
    ...rest
  } = options ?? {};

  return factory({
    baseUrl: "/api",
    ...rest,
    fetch: (input: RequestInfo | URL, init?: RequestInit) => {
      const nextHeaders = new Headers(init?.headers);
      const configured = typeof headers === "function" ? headers() : headers;
      for (const [key, value] of Object.entries(configured ?? {})) {
        if (value != null && !nextHeaders.has(key)) nextHeaders.set(key, value);
      }
      const method = (init?.method ?? "GET").toUpperCase();
      if (idempotency && WRITE_METHODS.has(method) && !nextHeaders.has("Idempotency-Key")) {
        nextHeaders.set("Idempotency-Key", crypto.randomUUID());
      }
      return fetchImpl(input, { ...init, credentials, headers: nextHeaders });
    },
  } as Parameters<TFactory>[0]) as ReturnType<TFactory>;
}

function snapshotKey(snapshot: DehydratedClient | null | undefined): string | null {
  return snapshot == null ? null : JSON.stringify(snapshot);
}

const WRITE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
