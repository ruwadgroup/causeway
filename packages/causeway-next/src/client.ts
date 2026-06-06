"use client";

import { Fragment, createElement, useEffect, useLayoutEffect, useRef } from "react";
import type { ReactNode } from "react";

import { isWriteMethod } from "@causewayjs/client";
import type {
  CausewayClient,
  ClientFactory,
  DehydratedClient,
  HeaderRecord,
} from "@causewayjs/client";
import {
  CausewayProvider,
  registerCausewayHydrationSnapshot,
  useOptionalCausewayClient,
  type CausewayFeedback,
} from "@causewayjs/react";

export type { ClientFactory, HeaderRecord };

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

const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

export function createHydrateClient<
  TFactory extends (options?: any) => any,
  TOptions extends object = Parameters<TFactory>[0] extends object
    ? NonNullable<Parameters<TFactory>[0]>
    : object,
>(factory: TFactory, options?: TOptions) {
  return function HydrateClient({ children, feedback, snapshot, state }: HydrateClientProps) {
    const hydrationState = state ?? snapshot;
    const hydrationKey = snapshotKey(hydrationState);
    const parentClient = useOptionalCausewayClient();
    const fallbackClient = useRef<CausewayClient | null>(null);
    if (parentClient === null && fallbackClient.current === null) {
      fallbackClient.current = factory(options) as CausewayClient;
    }
    const client = (parentClient ?? fallbackClient.current) as CausewayClient;

    // Apply the snapshot during render so boundary children read server data on
    // first render. Idempotent and keyed on the snapshot id, so re-renders
    // (incl. StrictMode/concurrent) never re-apply the same snapshot. Subscribers
    // already mounted are notified from the layout effect below.
    const lastHydration = useRef<{ client: CausewayClient; key: string | null } | null>(null);
    const last = lastHydration.current;
    if (hydrationState != null && (last?.client !== client || last.key !== hydrationKey)) {
      client.hydrate(hydrationState, { notify: false });
      lastHydration.current = { client, key: hydrationKey };
    }

    const lastNotified = useRef<{ client: CausewayClient; key: string | null } | null>(null);
    useIsomorphicLayoutEffect(() => {
      if (hydrationState == null) return;
      const prev = lastNotified.current;
      if (prev?.client === client && prev.key === hydrationKey) return;
      client.hydrate(hydrationState, { forceNotify: true });
      registerCausewayHydrationSnapshot(client, hydrationState);
      lastNotified.current = { client, key: hydrationKey };
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
        if (value == null || nextHeaders.has(key)) continue;
        nextHeaders.set(key, typeof value === "string" ? value : value.join(", "));
      }
      if (idempotency && isWriteMethod(init?.method) && !nextHeaders.has("Idempotency-Key")) {
        nextHeaders.set("Idempotency-Key", crypto.randomUUID());
      }
      return fetchImpl(input, { ...init, credentials, headers: nextHeaders });
    },
  } as Parameters<TFactory>[0]) as ReturnType<TFactory>;
}

function snapshotKey(snapshot: DehydratedClient | null | undefined): string | null {
  if (snapshot == null) return null;
  return snapshot.id ?? JSON.stringify(snapshot);
}
