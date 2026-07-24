import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

/** config 存储项目的 JavaScript 与 TypeScript 静态检查规则。 */
const config = tseslint.config(
  {
    ignores: [
      "dist/**",
      "release/**",
      "build/**",
      "node_modules/**",
      ".venv/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}", "tests/ui/**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-hooks/set-state-in-effect": "off",
    },
  },
  {
    files: ["electron/**/*.js", "scripts/**/*.mjs", "tests/electron/**/*.js"],
    languageOptions: { globals: globals.node },
  },
  {
    files: ["electron/preload.cjs"],
    languageOptions: { globals: globals.node },
    rules: { "@typescript-eslint/no-require-imports": "off" },
  },
);

export default config;
