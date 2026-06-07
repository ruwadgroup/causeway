import { defineConfig } from "tsdown";

export default defineConfig({
  entry: ["src/index.ts", "src/client.ts"],
  format: ["esm", "cjs"],
  dts: true,
  fixedExtension: false,
  sourcemap: true,
  target: "es2022",
  clean: true,
  deps: {
    neverBundle: ["@causewayjs/client", "@causewayjs/react", "react", "react-dom"],
  },
});
