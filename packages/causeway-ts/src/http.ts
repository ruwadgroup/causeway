export const WRITE_METHODS: ReadonlySet<string> = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export function isWriteMethod(method: string | undefined): boolean {
  return WRITE_METHODS.has((method ?? "GET").toUpperCase());
}
