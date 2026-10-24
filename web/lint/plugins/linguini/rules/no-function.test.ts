import { tester } from "../../rule-tester.ts"
import { noFunctionRule } from "./no-function.ts"

const noFunction = { messageId: "noFunction" }

const noOverload = { messageId: "noOverload" }

tester.run("linguini/no-function", noFunctionRule, {
  valid: [
    "const add = (a: number, b: number) => a + b",
    "const load = async () => { await fetch('/') }",
    "function* ids() { yield 1 }",
    "async function* pages() { yield 1 }",
    "const ids = function* () { yield 1 }",
    "class Counter { increment() { return 1 } }",
    "class Counter { get value() { return 1 } set value(next: number) {} }",
    "abstract class Shape { abstract area(): number }",
    "class Parser { parse(input: string): number; parse(input: number): number; parse(input: unknown) { return 1 } }",
    "const counter = { increment() { return 1 } }",
    "const counter = { get value() { return 1 } }",
    "const counter = { *ids() { yield 1 } }",
  ],
  invalid: [
    { name: "declaration", code: "function add(a: number, b: number) { return a + b }", errors: [noFunction] },
    { name: "async declaration", code: "async function load() {}", errors: [noFunction] },
    { name: "exported declaration", code: "export function add() {}", errors: [noFunction] },
    { name: "anonymous default export", code: "export default function () {}", errors: [noFunction] },
    { name: "const expression", code: "const add = function () {}", errors: [noFunction] },
    { name: "named expression", code: "const add = function add() {}", errors: [noFunction] },
    { name: "callback expression", code: "[1].map(function (value) { return value })", errors: [noFunction] },
    { name: "property expression", code: "const counter = { increment: function () {} }", errors: [noFunction] },
    { name: "declare function", code: "declare function parse(input: string): number", errors: [noOverload] },
    {
      name: "overload signatures",
      code: "function parse(input: string): number\nfunction parse(input: number): number\nfunction parse(input: string | number) { return 1 }",
      errors: [noOverload, noOverload, noFunction],
    },
  ],
})
