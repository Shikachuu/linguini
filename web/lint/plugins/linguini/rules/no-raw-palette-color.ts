import type { ESTree } from "vite-plus/lint/plugins"
import { defineRule } from "vite-plus/lint/plugins"

const UTILITIES =
  "bg|text|border(?:-[xytrblse])?|ring|ring-offset|outline|fill|stroke|from|via|to|decoration|shadow|accent|caret|divide|placeholder|inset-ring|inset-shadow|text-shadow|drop-shadow"

const PALETTE =
  "red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone|taupe|mauve|mist|olive"

const RAW_COLOR = new RegExp(
  String.raw`(?:^|[\s:!])((?:${UTILITIES})-(?:(?:${PALETTE})-\d{2,3}|\[(?:color:)?(?:#|(?:rgba?|hsla?|oklch|oklab|lch|lab)\()))`,
  "u",
)

export const noRawPaletteColorRule = defineRule({
  meta: {
    type: "suggestion",
    docs: { description: "Disallow Tailwind palette colours and arbitrary colour values in class names." },
    messages: {
      noRawPaletteColor: "Replace `{{match}}` with a design token from src/index.css, such as `text-success`.",
    },
  },
  createOnce(context) {
    const check = (node: ESTree.Node, text: string) => {
      const match = RAW_COLOR.exec(text)

      if (match !== null) context.report({ node, messageId: "noRawPaletteColor", data: { match: match[1] } })
    }

    return {
      Literal(node) {
        check(node, String(node.value))
      },
      TemplateElement(node) {
        check(node, node.value.cooked ?? node.value.raw)
      },
    }
  },
})
