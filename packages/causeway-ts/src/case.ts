import { isPlainObject } from "./utils.js";

interface OpaqueTree {
  opaque?: boolean;
  children?: Record<string, OpaqueTree>;
}

const camelCache = new Map<string, string>();
const snakeCache = new Map<string, string>();

function snakeToCamel(value: string): string {
  const hit = camelCache.get(value);
  if (hit !== undefined) return hit;
  const out = value.replace(/_([a-z0-9])/g, (_, char: string) => char.toUpperCase());
  camelCache.set(value, out);
  return out;
}

function camelToSnake(value: string): string {
  const hit = snakeCache.get(value);
  if (hit !== undefined) return hit;
  const out = value.replace(/[A-Z]/g, (char) => `_${char.toLowerCase()}`);
  snakeCache.set(value, out);
  return out;
}

function snakeToCamelDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(snakeToCamelDeep);
  if (!isPlainObject(value)) return value;
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(value)) out[snakeToCamel(key)] = snakeToCamelDeep(value[key]);
  return out;
}

function camelToSnakeDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(camelToSnakeDeep);
  if (!isPlainObject(value)) return value;
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(value)) out[camelToSnake(key)] = camelToSnakeDeep(value[key]);
  return out;
}

function buildOpaqueTree(paths: ReadonlyArray<string> | undefined): OpaqueTree | null {
  if (!paths || paths.length === 0) return null;
  const root: OpaqueTree = {};
  for (const path of paths) {
    let node = root;
    for (const segment of path.split(".")) {
      if (!segment) continue;
      const children = node.children ?? (node.children = {});
      node = children[segment] ?? (children[segment] = {});
    }
    node.opaque = true;
  }
  return root;
}

export function snakeToCamelDeepGuarded(
  value: unknown,
  paths: ReadonlyArray<string> | undefined,
): unknown {
  return snakeToCamelDeepWithTree(value, buildOpaqueTree(paths));
}

export function camelToSnakeDeepGuarded(
  value: unknown,
  paths: ReadonlyArray<string> | undefined,
): unknown {
  return camelToSnakeDeepWithTree(value, buildOpaqueTree(paths));
}

function snakeToCamelDeepWithTree(value: unknown, tree: OpaqueTree | null): unknown {
  if (tree === null) return snakeToCamelDeep(value);
  if (Array.isArray(value)) return value.map((item) => snakeToCamelDeepWithTree(item, tree));
  if (!isPlainObject(value)) return value;

  const out: Record<string, unknown> = {};
  for (const key of Object.keys(value)) {
    const renamed = snakeToCamel(key);
    const child = tree.children?.[renamed];
    if (child?.opaque) out[renamed] = value[key];
    else if (child) out[renamed] = snakeToCamelDeepWithTree(value[key], child);
    else out[renamed] = snakeToCamelDeep(value[key]);
  }
  return out;
}

function camelToSnakeDeepWithTree(value: unknown, tree: OpaqueTree | null): unknown {
  if (tree === null) return camelToSnakeDeep(value);
  if (Array.isArray(value)) return value.map((item) => camelToSnakeDeepWithTree(item, tree));
  if (!isPlainObject(value)) return value;

  const out: Record<string, unknown> = {};
  for (const key of Object.keys(value)) {
    const child = tree.children?.[key];
    const renamed = camelToSnake(key);
    if (child?.opaque) out[renamed] = value[key];
    else if (child) out[renamed] = camelToSnakeDeepWithTree(value[key], child);
    else out[renamed] = camelToSnakeDeep(value[key]);
  }
  return out;
}
