import { defineConfig } from "orval"

export default defineConfig({
  linguini: {
    input: { target: "./openapi.json" },
    output: {
      mode: "tags-split",
      target: "src/api/gen/endpoints",
      schemas: "src/api/gen/model",
      client: "react-query",
      httpClient: "fetch",
      mock: true,
      clean: true,
      override: {
        mutator: { path: "src/api/fetcher.ts", name: "apiFetch" },
        fetch: { includeHttpResponseReturnType: false },
      },
    },
  },
})
