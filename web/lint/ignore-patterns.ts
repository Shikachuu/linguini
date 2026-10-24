const agentDirectories = [
  ".agent",
  ".agents",
  ".claude",
  ".codex",
  ".continue",
  ".cursor",
  ".gemini",
  ".opencode",
  ".pi",
  ".roo",
  ".windsurf",
]

export const ignorePatterns = [
  ...agentDirectories.map((directory) => `**/${directory}/**`),
  "**/*.gen.ts",
  "dist/**",
  "openapi.json",
  "src/api/gen/**",
  "src/components/ai-elements/**",
  "src/components/ui/**",
]
