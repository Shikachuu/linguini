import { RuleTester } from "vite-plus/lint/plugins-dev"
import { describe, it } from "vite-plus/test"

RuleTester.describe = (text, fn) => {
  describe(text, fn)
}

RuleTester.it = (text, fn) => {
  it(text, fn)
}

RuleTester.itOnly = (text, fn) => {
  it.only(text, fn)
}

export const tester = new RuleTester({ languageOptions: { parserOptions: { lang: "ts" } } })
