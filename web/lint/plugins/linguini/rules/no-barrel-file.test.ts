import { tester } from "../../rule-tester.ts"
import { noBarrelFileRule } from "./no-barrel-file.ts"

const error = { messageId: "noBarrelFile" }

tester.run("linguini/no-barrel-file", noBarrelFileRule, {
  valid: [
    "export const value = 1",
    "const value = 1\nexport { value }",
    "import { value } from './value'\nexport { value }",
    "export type * from './types'",
    "export type { Shape } from './shape'",
    "export { type Shape, type Size } from './shape'",
  ],
  invalid: [
    { name: "star", code: "export * from './value'", errors: [error] },
    { name: "namespace star", code: "export * as values from './value'", errors: [error] },
    { name: "named", code: "export { value } from './value'", errors: [error] },
    { name: "default", code: "export { default as Button } from './button'", errors: [error] },
    { name: "mixed type and value", code: "export { type Shape, area } from './shape'", errors: [error] },
    { name: "empty specifiers", code: "export {} from './side-effect'", errors: [error] },
    { name: "each statement", code: "export * from './a'\nexport * from './b'", errors: [error, error] },
  ],
})
