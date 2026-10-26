import { tester } from "../../rule-tester.ts"
import { noRawPaletteColorRule } from "./no-raw-palette-color.ts"

const error = { messageId: "noRawPaletteColor" }

tester.run("linguini/no-raw-palette-color", noRawPaletteColorRule, {
  valid: [
    "const className = 'text-success bg-primary/10 border-border'",
    "const className = 'bg-black/50 text-white'",
    "const className = 'max-w-content size-[1.2em] grid-cols-4'",
    "const label = 'red-500 is a hex colour name'",
    `const className = \`text-\${tone}-600\``,
    "const colour = 'oklch(0.5 0.1 40)'",
    "const className = 'bg-transparent text-current bg-[var(--primary)] hover:bg-[color-mix(in_oklch,var(--secondary),var(--foreground)_5%)]'",
  ],
  invalid: [
    { name: "text palette colour", code: "const className = 'size-4 text-green-600'", errors: [error] },
    { name: "variant prefix", code: "const className = 'hover:bg-blue-500'", errors: [error] },
    { name: "opacity modifier", code: "const className = 'bg-red-500/20'", errors: [error] },
    { name: "important modifier", code: "const className = '!text-zinc-900'", errors: [error] },
    { name: "side border", code: "const className = 'border-l-amber-400'", errors: [error] },
    { name: "arbitrary hex", code: "const className = 'bg-[#be4a1b]'", errors: [error] },
    { name: "arbitrary oklch", code: "const className = 'text-[oklch(0.5_0.1_40)]'", errors: [error] },
    { name: "type-hinted arbitrary colour", code: "const className = 'bg-[color:#be4a1b]'", errors: [error] },
    { name: "text shadow", code: "const className = 'text-shadow-red-500'", errors: [error] },
    { name: "drop shadow", code: "const className = 'drop-shadow-zinc-900/50'", errors: [error] },
    { name: "cn object key", code: "cn({ 'text-red-500': failed })", errors: [error] },
    {
      name: "jsx class name",
      code: "const Icon = () => <span className='size-4 text-green-600' />",
      languageOptions: { parserOptions: { lang: "tsx" } },
      errors: [error],
    },
    { name: "template literal", code: `const className = \`p-2 \${active} text-gray-500\``, errors: [error] },
  ],
})
