import type { OxfmtConfig } from "vite-plus/fmt"

import { ignorePatterns } from "./ignore-patterns.ts"

export const formatter = {
  printWidth: 120,
  tabWidth: 2,
  useTabs: false,
  endOfLine: "lf",
  bracketSpacing: true,
  singleQuote: false,
  semi: false,
  trailingComma: "all",
  sortImports: {
    groups: ["builtin", "external", ["internal", "subpath"], ["parent", "sibling", "index"], "unknown"],
    newlinesBetween: false,
    partitionByNewline: true,
  },
  sortTailwindcss: {
    functions: ["clsx", "cn", "cva", "tw", "twMerge"],
  },
  ignorePatterns: [...ignorePatterns, "src/index.css"],
} satisfies OxfmtConfig
