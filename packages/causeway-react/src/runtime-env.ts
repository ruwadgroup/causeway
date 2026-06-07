// Runtime/environment probes shared across the hooks. Kept dependency-free so
// they're safe to import from any module (including in a Node/SSR context).

import { useEffect, useLayoutEffect } from "react";

// `useLayoutEffect` warns when run on the server; fall back to `useEffect`
// there. Resolved once at module load — the runtime doesn't change underfoot.
export const useIsomorphicLayoutEffect =
  typeof window === "undefined" ? useEffect : useLayoutEffect;

export function isBrowserRuntime(): boolean {
  return typeof window !== "undefined";
}

export function isDevRuntime(): boolean {
  const env = (globalThis as { process?: { env?: { NODE_ENV?: string } } }).process?.env?.NODE_ENV;
  return env !== "production";
}
