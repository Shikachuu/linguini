import { spawnSync } from "node:child_process"
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { createRequire } from "node:module"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import { afterAll, beforeAll, expect, it } from "vite-plus/test"

const vitePlus = createRequire(createRequire(import.meta.url).resolve("vite-plus/package.json"))

const oxlint = join(dirname(vitePlus.resolve("oxlint/package.json")), "bin/oxlint")

const probeRoot = mkdtempSync(join(tmpdir(), "anti-slop-spacing-"))

const config = join(probeRoot, "oxlint.json")

const first = join(probeRoot, "first.ts")

const second = join(probeRoot, "second.ts")

const runSpacingLint = (...args: string[]) => {
  const result = spawnSync(oxlint, ["--config", config, ...args], { encoding: "utf8" })

  return { status: result.status, output: `${result.stdout}\n${result.stderr}` }
}

const readProbes = () => [readFileSync(first, "utf8"), readFileSync(second, "utf8")]

beforeAll(() => {
  writeFileSync(
    config,
    JSON.stringify({
      jsPlugins: [{ name: "anti-slop", specifier: join(import.meta.dirname, "../index.ts") }],
      rules: { "anti-slop/require-readable-spacing": "error" },
    }),
  )
  writeFileSync(first, "export const a = 1;\n/** Attached to b. */\nexport const b = 2;\n")
  writeFileSync(second, "export function f() {\nconst a = 1;\nconst b = 2;\nreturn a + b;\n}\n")
})

afterAll(() => {
  rmSync(probeRoot, { recursive: true, force: true })
})

it("rejects, fixes, and stays stable through the oxlint CLI", () => {
  const rejected = runSpacingLint(first, second)
  expect(rejected).toMatchObject({ status: 1 })
  expect(rejected.output).toContain("require-readable-spacing")

  const fixed = runSpacingLint("--fix", first, second)
  expect(fixed).toMatchObject({ status: 0 })
  expect(readProbes()).toEqual([
    "export const a = 1;\n\n/** Attached to b. */\nexport const b = 2;\n",
    "export function f() {\nconst a = 1;\nconst b = 2;\n\nreturn a + b;\n}\n",
  ])

  const stable = readProbes()
  const clean = runSpacingLint(first, second)
  expect(clean).toMatchObject({ status: 0 })
  const repeated = runSpacingLint("--fix", first, second)
  expect(repeated).toMatchObject({ status: 0 })
  expect(readProbes()).toEqual(stable)
})
