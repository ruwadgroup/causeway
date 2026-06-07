// The provider + context accessors. `CausewayContext` is exported for the hooks
// that need the full provider value (e.g. mutation feedback); only the provider
// and the two accessors are re-exported as public API from `index.ts`.

import { createContext, createElement, useContext, useMemo } from "react";
import type { ReactElement, ReactNode } from "react";

import type { CausewayClient } from "@causewayjs/client";

export interface CausewayFeedback {
  loading?: (message: string, id: string) => unknown;
  success?: (message: string, id: string) => unknown;
  error?: (message: string, id: string) => unknown;
}

export interface ProviderValue {
  client: CausewayClient;
  feedback?: CausewayFeedback;
}

export interface CausewayProviderProps {
  client: CausewayClient;
  feedback?: CausewayFeedback;
  children?: ReactNode;
}

export const CausewayContext = createContext<ProviderValue | null>(null);

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
