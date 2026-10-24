import { tester } from "../../rule-tester.ts"
import { noDeleteRule } from "./no-delete.ts"

const error = { messageId: "noDelete" }

tester.run("linguini/no-delete", noDeleteRule, {
  valid: [
    "const { removed, ...rest } = owner",
    "cache.delete(key)",
    "owner.value = undefined",
    "const value = typeof owner",
  ],
  invalid: [
    { name: "static key", code: "delete owner.value", errors: [error] },
    { name: "computed key", code: "delete owner[key]", errors: [error] },
    { name: "array element", code: "delete items[0]", errors: [error] },
  ],
})
