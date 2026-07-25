import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/** 返回渲染层构建配置。 */
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { host: "127.0.0.1", port: 5276, strictPort: true },
  test: {
    environment: "happy-dom",
    setupFiles: "./tests/ui/setup.ts",
    // Playwright 的桌面用例由独立 runner 执行，避免 Vitest 加载其中的 test() 注册。
    exclude: ["e2e/**", "**/node_modules/**", "**/dist/**"],
  },
});
