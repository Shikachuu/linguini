import type { ESTree } from "vite-plus/lint/plugins"

export type VisitorKeys = Readonly<Record<string, readonly string[]>>

const isNode = (value: unknown): value is ESTree.Node => value instanceof Object && "type" in value && "range" in value

export const childNodes = (node: ESTree.Node, visitorKeys: VisitorKeys): readonly ESTree.Node[] => {
  const keys = new Set(visitorKeys[node.type])
  const fields: readonly (readonly [string, unknown])[] = Object.entries(node)

  return fields.flatMap(([key, value]) => (keys.has(key) ? [value].flat() : [])).filter((value) => isNode(value))
}
