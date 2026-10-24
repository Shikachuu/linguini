import { tester } from "../../rule-tester.ts"
import { noUselessElseRule } from "./no-useless-else.ts"

const error = { messageId: "noUselessElse" }

tester.run("linguini/no-useless-else", noUselessElseRule, {
  valid: [
    "const f = (x: number) => { if (x < 0) { return 0 } return x }",
    "const f = (x: number) => { if (x < 0) { log(x) } else { return x } }",
    "const f = (x: number) => { if (x < 0) { log(x) } else if (x > 0) { return x } else { log(0) } }",
    "const f = (x: number) => { if (x < 0) {} else { return x } }",
    "const f = (x: number) => { if (x < 0) { return 0; log(x) } else { return x } }",
  ],
  invalid: [
    {
      name: "return",
      code: "const f = (x: number) => { if (x < 0) { return 0 } else { return x } }",
      errors: [error],
    },
    {
      name: "throw without block",
      code: "const f = (x: number) => { if (x < 0) throw new RangeError()\nelse return x }",
      errors: [error],
    },
    { name: "break", code: "while (x > 0) { if (f(x)) { break } else { x++ } }", errors: [error] },
    { name: "continue", code: "for (const x of xs) { if (x) { continue } else { log(x) } }", errors: [error] },
    {
      name: "else if chain",
      code: "const f = (x: number) => { if (x < 0) { return -1 } else if (x > 0) { return 1 } else { return 0 } }",
      errors: [error, error],
    },
    {
      name: "else if after exit",
      code: "const f = (x: number) => { if (x < 0) { return 0 } else if (x > 0) { log(x) } }",
      errors: [error],
    },
    {
      name: "nested block",
      code: "const f = (x: number) => { if (x < 0) { { return 0 } } else { return x } }",
      errors: [error],
    },
  ],
})
