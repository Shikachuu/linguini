# Lint and format config

The oxlint and oxfmt configuration for the web app. It is copied from [`@skinapp/lint-config`](https://github.com/kovapatrik/skinapp/tree/main/packages/lint-config) with the same rules. Only the ignore patterns, the custom plugin name and the import paths differ.

## Usage

Vite+ reads lint and format settings from the `lint` and `fmt` blocks in `web/vite.config.ts`, so there is no `oxlint.config.ts` or `oxfmt.config.ts`. `vite.config.ts` spreads `react` from `lint/oxlint.ts` into `lint` and passes `formatter` from `lint/oxfmt.ts` as `fmt`. It also adds the `vite-plus/prefer-vite-plus-imports` rule and the `typeAware` and `typeCheck` options.

`vp check` runs both. `vp lint --fix` and `vp fmt` apply the fixes.

Plugin code imports the oxlint API from `vite-plus/lint/plugins` and `vite-plus/lint/plugins-dev`, never from `@oxlint/plugins` or `oxlint`. That way the plugins always use the oxlint copy that Vite+ runs.

## What the presets enable

- The `correctness`, `suspicious`, `perf` and `pedantic` categories, all at `error`.
- The rules listed in `oxlint.ts`.
- All `anti-slop` rules plus `oxc/no-accumulating-spread`.
- The `linguini` rules in `plugins/linguini`.

The `base` preset fits non-React code. The `react` preset adds the `react` and `jsx-a11y` plugins, and the web app uses it.

`typescript/prefer-readonly-parameter-types` is off. React props and oxlint AST nodes are deeply mutable library types, so almost no parameter can pass it.

Config files (`*.config.{ts,mts,js,mjs}`) may use default exports and `process.env`. Test files (`*.test.{ts,tsx}`) get the `vitest` plugin. The plugin entry points (`lint/plugins/*/index.ts`) may use default exports.

`ignore-patterns.ts` skips agent directories, the build output, and code that the app generates or vendors: `src/api/gen` (orval), `src/routeTree.gen.ts` (TanStack Router), `src/components/ui` (shadcn) and `src/components/ai-elements` (AI Elements). The formatter also skips `src/index.css` and reads it as the Tailwind stylesheet when it sorts classes.

## Custom rules

The code in `plugins/linguini` is the `skinapp` plugin renamed:

- `no-function` reports function declarations, function expressions and `declare function` overloads. It allows generators and class or object methods.
- `no-enum` reports every `enum`, including `const enum` and `declare enum`.
- `no-delete` reports every `delete` expression.
- `no-barrel-file` reports value re-exports (`export * from`, `export { x } from`). It allows type-only re-exports.
- `no-useless-else` reports an `else` that follows a branch ending in `return`, `throw`, `break` or `continue`.

skinapp forked `plugins/anti-slop` from [dmmulroy/anti-slop](https://github.com/dmmulroy/anti-slop). The fork has these changes:

- The code uses arrow functions only.
- The `allowInTypeGuards` option of `no-runtime-typeof` is removed.
- The `markers` option of `require-safety-comment-for-type-assertion` is removed, so the marker is always `SAFETY:`.

`plugins/anti-slop/stylistic` is adapted from ESLint Stylistic `padding-line-between-statements`. Both upstream MIT notices are in `plugins/anti-slop/LICENSE`.

Every rule has RuleTester tests next to it, and `vp test` runs them with the app tests.
