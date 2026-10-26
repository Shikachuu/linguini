import { eslintCompatPlugin } from "vite-plus/lint/plugins"

import { noBarrelFileRule } from "./rules/no-barrel-file.ts"
import { noDeleteRule } from "./rules/no-delete.ts"
import { noEnumRule } from "./rules/no-enum.ts"
import { noFunctionRule } from "./rules/no-function.ts"
import { noRawPaletteColorRule } from "./rules/no-raw-palette-color.ts"
import { noUselessElseRule } from "./rules/no-useless-else.ts"

const linguiniPlugin = eslintCompatPlugin({
  meta: { name: "linguini" },
  rules: {
    "no-barrel-file": noBarrelFileRule,
    "no-delete": noDeleteRule,
    "no-enum": noEnumRule,
    "no-function": noFunctionRule,
    "no-raw-palette-color": noRawPaletteColorRule,
    "no-useless-else": noUselessElseRule,
  },
})

export default linguiniPlugin
