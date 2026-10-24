import { defineRule } from "vite-plus/lint/plugins"

import type { ESTree } from "vite-plus/lint/plugins"

const isExistenceProbe = (node: ESTree.UnaryExpression): boolean => {
  const parent = node.parent

  if (parent.type !== "BinaryExpression") return false

  if (!["===", "!==", "==", "!="].includes(parent.operator)) return false
  const other = parent.left === node ? parent.right : parent.left

  return other.type === "Literal" && other.value === "undefined"
}

export const noRuntimeTypeofRule = defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow runtime typeof checks; external values must be decoded into meaningful types at their I/O boundary.",
    },
    messages: {
      runtimeTypeof:
        "A `typeof` check narrows a representation without establishing its contract. Parse input at its I/O boundary, then branch on the domain value.",
    },
    schema: [],
  },
  createOnce(context) {
    return {
      UnaryExpression(node) {
        if (node.operator === "typeof" && !isExistenceProbe(node)) {
          context.report({ node, messageId: "runtimeTypeof" })
        }
      },
    }
  },
})
