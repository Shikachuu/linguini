import { defineConfig } from "orval"

export default defineConfig({
  linguini: {
    input: { target: "./openapi.json" },
    output: {
      mode: "tags-split",
      target: "src/api/gen/endpoints",
      schemas: { path: "src/api/gen/model", type: "zod" },
      client: "react-query",
      httpClient: "fetch",
      mock: true,
      clean: true,
      override: {
        mutator: { path: "src/api/fetcher.ts", name: "apiFetch" },
        fetch: { includeHttpResponseReturnType: false, runtimeValidation: true },
        includeZodSchemaInArguments: true,
      },
    },
  },
})
