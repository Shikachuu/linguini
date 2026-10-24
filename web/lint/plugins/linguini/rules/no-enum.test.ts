import { tester } from "../../rule-tester.ts"
import { noEnumRule } from "./no-enum.ts"

const error = { messageId: "noEnum" }

tester.run("linguini/no-enum", noEnumRule, {
  valid: ["type Direction = 'up' | 'down'", "const Direction = { Up: 'up', Down: 'down' } as const"],
  invalid: [
    { name: "enum", code: "enum Direction { Up, Down }", errors: [error] },
    { name: "const enum", code: "const enum Direction { Up, Down }", errors: [error] },
    { name: "declare enum", code: "declare enum Direction { Up, Down }", errors: [error] },
    { name: "exported enum", code: "export enum Direction { Up = 'up' }", errors: [error] },
  ],
})
