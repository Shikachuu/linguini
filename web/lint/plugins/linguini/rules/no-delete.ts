import { defineRule } from "vite-plus/lint/plugins"

export const noDeleteRule = defineRule({
  meta: {
    type: "suggestion",
    docs: { description: "Disallow the `delete` operator." },
    messages: {
      noDelete: "Avoid `delete`; build a new value without the key, or use a `Map` for dynamic keys.",
    },
  },
  createOnce(context) {
    return {
      UnaryExpression(node) {
        if (node.operator === "delete") context.report({ node, messageId: "noDelete" })
      },
    }
  },
})
