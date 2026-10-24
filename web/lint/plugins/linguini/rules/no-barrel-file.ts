import { defineRule } from "vite-plus/lint/plugins"

export const noBarrelFileRule = defineRule({
  meta: {
    type: "suggestion",
    docs: { description: "Disallow re-exporting values from other modules." },
    messages: {
      noBarrelFile: "Import from the source module instead of re-exporting it; barrel files grow the module graph.",
    },
  },
  createOnce(context) {
    return {
      ExportAllDeclaration(node) {
        if (node.exportKind !== "type") context.report({ node, messageId: "noBarrelFile" })
      },
      ExportNamedDeclaration(node) {
        if (node.source === null || node.exportKind === "type") return

        if (node.specifiers.length > 0 && node.specifiers.every((specifier) => specifier.exportKind === "type")) return
        context.report({ node, messageId: "noBarrelFile" })
      },
    }
  },
})
