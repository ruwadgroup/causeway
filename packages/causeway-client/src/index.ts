import type { CallOptions, CausewayClient } from "@causewayjs/ts";

export {
  CausewayError,
  DEFAULT_FORWARDED_HEADERS,
  createRouteKeyClient as createClient,
  forwardHeaders,
  isWriteMethod,
  normalizeError,
  unwrapResult,
  WRITE_METHODS,
} from "@causewayjs/ts";

export type {
  CallOptions,
  CausewayClient,
  ClientConfig,
  DehydratedClient,
  DehydratedQuery,
  HeaderRecord,
  HeaderRecordValue,
  HeaderSource,
  HeadersLike,
  HydrateOptions,
  QueryState,
  RouteDescriptor,
  RouteMeta,
} from "@causewayjs/ts";

export interface Register {}

export type RouteInputValue = Record<string, unknown> | void;

export type ClientFactory<TClient = CausewayClient, TOptions extends object = object> = (
  options?: TOptions,
) => TClient;

type RegisteredValue<TKey extends PropertyKey, TFallback> = TKey extends keyof Register
  ? Register[TKey]
  : TFallback;

export type RegisteredRouteKey = Extract<RegisteredValue<"routeKey", string>, string>;
export type RegisteredQueryRouteKey = Extract<RegisteredValue<"queryRouteKey", string>, string>;
export type RegisteredMutationRouteKey = Extract<
  RegisteredValue<"mutationRouteKey", string>,
  string
>;

export type HasRegisteredRoutes = string extends RegisteredRouteKey ? false : true;
export type UnregisteredRouteKey = HasRegisteredRoutes extends true ? never : string;

export type RegisteredRouteInput<K extends string> = Register extends {
  routeInput: infer TInput;
}
  ? K extends keyof TInput
    ? TInput[K]
    : RouteInputValue
  : RouteInputValue;

export type RegisteredRouteData<K extends string> = Register extends { routeData: infer TData }
  ? K extends keyof TData
    ? TData[K]
    : unknown
  : unknown;

export type RegisteredRouteError<K extends string> = Register extends { routeError: infer TError }
  ? K extends keyof TError
    ? TError[K]
    : unknown
  : unknown;

export type RegisteredQueryArgs<K extends string> = [RegisteredRouteInput<K>] extends [void]
  ? [input?: void, call?: CallOptions]
  : [input: RegisteredRouteInput<K>, call?: CallOptions];

export interface QueryOptions<
  K extends string = string,
  TInput extends RouteInputValue = RouteInputValue,
> {
  routeKey: K;
  input: TInput;
  call?: CallOptions;
}

export function queryOptions<K extends RegisteredQueryRouteKey>(
  routeKey: K,
  ...args: RegisteredQueryArgs<K>
): QueryOptions<K, RegisteredRouteInput<K>>;
export function queryOptions(
  routeKey: UnregisteredRouteKey,
  input?: RouteInputValue,
  call?: CallOptions,
): QueryOptions;
export function queryOptions(
  routeKey: string,
  input?: RouteInputValue,
  call?: CallOptions,
): QueryOptions {
  return { routeKey, input, call };
}
