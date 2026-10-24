import { defineRule } from "vite-plus/lint/plugins"
import type { ESTree } from "vite-plus/lint/plugins"

const FORBIDDEN_SYMBOL_NAME = "shape"

const containsForbiddenSymbolName = (name: string): boolean => {
  return name.toLowerCase().includes(FORBIDDEN_SYMBOL_NAME)
}

const isBorrowedMemberName = (node: ESTree.Node): boolean => {
  const parent = node.parent

  if (parent?.type !== "MemberExpression") return false

  return parent.property === node && !parent.computed
}

export const noForbiddenTermInSymbolNamesRule = defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        'Disallow the case-insensitive substring "shape" in JavaScript, TypeScript, private, and JSX symbol names.',
    },
    messages: {
      forbiddenSymbolName:
        'Rename symbol "{{name}}" for its domain role; "shape" describes structure rather than ownership.',
    },
  },
  createOnce(context) {
    const reportForbiddenSymbolName = (node: ESTree.Node & { name: string }) => {
      if (!containsForbiddenSymbolName(node.name) || isBorrowedMemberName(node)) return
      context.report({
        node,
        messageId: "forbiddenSymbolName",
        data: { name: node.name },
      })
    }

    return {
      Identifier: reportForbiddenSymbolName,
      PrivateIdentifier: reportForbiddenSymbolName,
      JSXIdentifier: reportForbiddenSymbolName,
    }
  },
})
