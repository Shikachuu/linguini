import { fileURLToPath, URL } from "node:url"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react"
import { defineConfig, lazyPlugins } from "vite-plus"
import { formatter } from "./lint/oxfmt.ts"
import { react as reactLint } from "./lint/oxlint.ts"

export default defineConfig({
  fmt: {
    ...formatter,
    sortTailwindcss: { ...formatter.sortTailwindcss, stylesheet: "./src/index.css" },
  },
  lint: {
    ...reactLint,
    jsPlugins: [...reactLint.jsPlugins, { name: "vite-plus", specifier: "vite-plus/oxlint-plugin" }],
    rules: {
      ...reactLint.rules,
      "vite-plus/prefer-vite-plus-imports": "error",
    },
    overrides: [
      ...reactLint.overrides,
      {
        files: ["lint/plugins/*/index.ts"],
        rules: { "import/no-default-export": "off" },
      },
      {
        files: ["src/routes/**"],
        rules: { "react/only-export-components": "off" },
      },
      {
        files: ["src/router.tsx"],
        rules: { "typescript/consistent-type-definitions": "off" },
      },
    ],
    options: {
      typeAware: true,
      typeCheck: true,
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}", "lint/**/*.test.ts"],
    setupFiles: ["src/test/setup.ts"],
  },
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  plugins: lazyPlugins(() => [tanstackRouter({ target: "react", autoCodeSplitting: true }), react(), tailwindcss()]),
})
