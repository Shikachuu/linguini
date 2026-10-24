import { defineRule } from "vite-plus/lint/plugins"
import type { ESTree } from "vite-plus/lint/plugins"

const isMethod = (node: ESTree.Function) => {
  const { parent } = node

  if (parent.type === "Property") return parent.method || parent.kind !== "init"

  return parent.type === "MethodDefinition" || parent.type === "TSAbstractMethodDefinition"
}

export const noFunctionRule = defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Disallow the `function` keyword outside generators; declare functions as arrow functions.",
    },
    messages: {
      noFunction: "Replace this `function` with an arrow function assigned to a `const`.",
      noOverload: "Replace `function` overload signatures with an overloaded type on a `const` arrow function.",
    },
  },
  createOnce(context) {
    return {
      FunctionDeclaration(node) {
        if (!node.generator) context.report({ node, messageId: "noFunction" })
      },
      FunctionExpression(node) {
        if (!node.generator && !isMethod(node)) context.report({ node, messageId: "noFunction" })
      },
      TSDeclareFunction(node) {
        context.report({ node, messageId: "noOverload" })
      },
    }
  },
})
