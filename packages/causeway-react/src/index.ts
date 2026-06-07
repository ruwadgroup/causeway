"use client";

export {
  CausewayProvider,
  useCausewayClient,
  useOptionalCausewayClient,
  type CausewayFeedback,
  type CausewayProviderProps,
} from "./context.js";
export { registerCausewayHydrationSnapshot } from "./hydration.js";
export { useQuery, type QueryHookOptions, type QueryHookResult } from "./use-query.js";
export {
  useMutation,
  type MutationFeedback,
  type MutationHookOptions,
  type MutationHookResult,
} from "./use-mutation.js";
export {
  useSubscription,
  type SubscriptionHookOptions,
  type SubscriptionHookResult,
  type SubscriptionStatus,
} from "./use-subscription.js";

export { queryOptions } from "@causewayjs/client";
export type { QueryOptions } from "@causewayjs/client";
