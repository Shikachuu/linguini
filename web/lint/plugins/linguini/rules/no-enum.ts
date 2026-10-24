import { defineRule } from "vite-plus/lint/plugins"

export const noEnumRule = defineRule({
  meta: {
    type: "suggestion",
    docs: { description: "Disallow TypeScript enums." },
    messages: {
      noEnum: "Replace this enum with a union of literal types or an `as const` object.",
    },
  },
  createOnce(context) {
    return {
      TSEnumDeclaration(node) {
        context.report({ node, messageId: "noEnum" })
      },
    }
  },
})
