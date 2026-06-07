import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  resolve: {
    alias: {
      "@causewayjs/client": fileURLToPath(
        new URL("../causeway-client/src/index.ts", import.meta.url),
      ),
      "@causewayjs/ts": fileURLToPath(new URL("../causeway-ts/src/index.ts", import.meta.url)),
    },
  },
  test: {
    environment: "happy-dom",
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      include: ["src/**/*.ts"],
    },
  },
});
