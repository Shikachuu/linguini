import { defineRule } from "vite-plus/lint/plugins"
import type { ESTree } from "vite-plus/lint/plugins"

const breaksEarly = (statement: ESTree.Statement): boolean => {
  if (statement.type === "BlockStatement") {
    const last = statement.body.at(-1)

    return last !== undefined && breaksEarly(last)
  }

  return (
    statement.type === "ReturnStatement" ||
    statement.type === "ThrowStatement" ||
    statement.type === "BreakStatement" ||
    statement.type === "ContinueStatement"
  )
}

const chainBreaksEarly = (node: ESTree.IfStatement): boolean => {
  if (!breaksEarly(node.consequent)) return false
  const { parent } = node

  return parent.type !== "IfStatement" || parent.alternate !== node || chainBreaksEarly(parent)
}

export const noUselessElseRule = defineRule({
  meta: {
    type: "suggestion",
    docs: { description: "Disallow `else` after an `if` chain whose branches all return, throw, break, or continue." },
    messages: {
      noUselessElse: "Drop this `else`; every earlier branch already exits, so its body can follow the `if`.",
    },
  },
  createOnce(context) {
    return {
      IfStatement(node) {
        if (node.alternate !== null && chainBreaksEarly(node)) {
          context.report({ node: node.alternate, messageId: "noUselessElse" })
        }
      },
    }
  },
})
