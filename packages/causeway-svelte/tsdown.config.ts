import { defineConfig } from "tsdown";

export default defineConfig({
  entry: ["src/index.ts", "src/server.ts"],
  format: ["esm", "cjs"],
  dts: true,
  fixedExtension: false,
  sourcemap: true,
  target: "es2022",
  clean: true,
  external: ["svelte", "svelte/store", "@causewayjs/client"],
});
