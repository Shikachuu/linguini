# Linguini web app

This is a React SPA built with Vite+ (`vite-plus`, CLI `vp`). FastAPI serves `web/dist` on the same origin in development and in production.

- mise pins Node and pnpm, and there is no global `vp`. Run it as `pnpm exec vp <command>`, or use the repo-level mise tasks: `mise run dev`, `check`, `fmt`, `test`, `build` and `gen`.
- `vp <name>` runs a built-in command, and `vp run <name>` runs a `vite.config.ts` task. The docs are in `node_modules/vite-plus/docs`.
- Import test helpers from `vite-plus/test` and config helpers from `vite-plus`, never from `vitest` or `vite`.
- The lint and format rules live in `lint/` (see `lint/README.md`) and `vite.config.ts` spreads them into its `lint` and `fmt` blocks. Fix findings in the code instead of disabling rules. A new or changed custom rule needs a RuleTester test next to it.
- Don't edit generated code:
  - `src/api/gen/**` comes from orval. It is built from `openapi.json` by `mise run gen`.
  - `src/routeTree.gen.ts` comes from the TanStack Router plugin.
  - `src/components/ui/**` comes from shadcn.
  - `src/components/ai-elements/**` comes from AI Elements.
- Every non-GET `/api/*` call needs the header `X-Requested-With: linguini`. `src/api/fetcher.ts` adds it to calls made through the generated client. Anything else, such as the chat transport, has to add it by hand.
- Don't set `compilerOptions.baseUrl`, because the Vite+ type checker skips type checks when it is set.
