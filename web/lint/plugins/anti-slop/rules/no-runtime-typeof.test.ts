import { tester } from "../../rule-tester.ts"

import { noRuntimeTypeofRule } from "./no-runtime-typeof.ts"

const error = { messageId: "runtimeTypeof" }

tester.run("anti-slop/no-runtime-typeof", noRuntimeTypeofRule, {
  valid: [
    'const isServer = typeof document === "undefined";',
    'const hasStorage = typeof localStorage !== "undefined";',
    'if (typeof globalThis.crypto === "undefined") throw new Error("no crypto");',
    'const missing = "undefined" === typeof process;',
    "const value = input;",
  ],
  invalid: [
    { code: 'if (typeof input === "string") use(input);', errors: [error] },
    { code: "if (typeof input === undefined) use(input);", errors: [error] },
    {
      code: 'function isString(value: unknown): value is string { return typeof value === "string"; }',
      errors: [error],
    },
    {
      code: 'const isString = (value: unknown): value is string => typeof value === "string";',
      errors: [error],
    },
  ],
})
