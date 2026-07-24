import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/** 返回渲染层构建配置。 */
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { host: "127.0.0.1", port: 5276, strictPort: true },
  test: { environment: "happy-dom", setupFiles: "./tests/ui/setup.ts" },
});
