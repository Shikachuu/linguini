import type { ESTree, SourceCode } from "vite-plus/lint/plugins"

import {
  isClosingBraceToken,
  isFunction,
  isNotSemicolonToken,
  isSingleLine,
  skipChainExpression,
} from "./padding-line-ast.ts"

type NodeTest = (node: ESTree.Node, sourceCode: SourceCode) => boolean

export type NodeTestObject = {
  readonly test: NodeTest
}

const CJS_EXPORT = /^(?:module\s*\.\s*)?exports(?:\s*\.|\s*\[|$)/u

const CJS_IMPORT = /^require\(/u

const newKeywordTester = (type: string | readonly string[], keyword: string): NodeTestObject => {
  return {
    test(node, sourceCode): boolean {
      const isSameKeyword = sourceCode.getFirstToken(node)?.value === keyword
      const isSameType = Array.isArray(type) ? type.includes(node.type) : type === node.type

      return isSameKeyword && isSameType
    },
  }
}

const newNodeTypeTester = (type: string): NodeTestObject => {
  return {
    test: (node): boolean => node.type === type,
  }
}

const isIIFEStatement = (node: ESTree.Node): boolean => {
  if (node.type !== "ExpressionStatement") return false
  let expression = skipChainExpression(node.expression)

  if (expression.type === "UnaryExpression") expression = skipChainExpression(expression.argument)

  if (expression.type !== "CallExpression") return false
  let callee: ESTree.Node = expression.callee

  while (callee.type === "SequenceExpression") {
    const lastExpression = callee.expressions.at(-1)

    if (lastExpression === undefined) throw new Error("Padding rule invariant: sequence expression is empty")
    callee = lastExpression
  }

  return isFunction(callee)
}

const isCJSRequire = (node: ESTree.Node): boolean => {
  if (node.type !== "VariableDeclaration") return false
  let call = node.declarations[0]?.init ?? null

  if (call === null) return false

  while (call.type === "MemberExpression") call = call.object

  return call.type === "CallExpression" && call.callee.type === "Identifier" && call.callee.name === "require"
}

const isBlockLikeStatement = (node: ESTree.Node, sourceCode: SourceCode): boolean => {
  if (node.type === "DoWhileStatement" && node.body.type === "BlockStatement") return true

  if (isIIFEStatement(node)) return true
  const lastToken = sourceCode.getLastToken(node, isNotSemicolonToken)

  const belongingNode =
    lastToken && isClosingBraceToken(lastToken) ? sourceCode.getNodeByRangeIndex(lastToken.range[0]) : null

  return !!belongingNode && (belongingNode.type === "BlockStatement" || belongingNode.type === "SwitchStatement")
}

const isDirective = (node: ESTree.Node): boolean => {
  return node.type === "ExpressionStatement" && (node.directive ?? null) !== null
}

const isCJSExport = (node: ESTree.Node): boolean => {
  if (node.type !== "ExpressionStatement" || node.expression.type !== "AssignmentExpression") return false
  let left = node.expression.left

  if (left.type !== "MemberExpression") return false

  while (left.object.type === "MemberExpression") left = left.object

  return (
    left.object.type === "Identifier" &&
    (left.object.name === "exports" ||
      (left.object.name === "module" && left.property.type === "Identifier" && left.property.name === "exports"))
  )
}

const isExpression = (node: ESTree.Node): boolean => {
  return node.type === "ExpressionStatement" && !isDirective(node)
}

const maybeMultilineStatementTypes = {
  "block-like": { test: isBlockLikeStatement },
  expression: { test: isExpression },
  return: newKeywordTester("ReturnStatement", "return"),
  export: newKeywordTester(["ExportAllDeclaration", "ExportDefaultDeclaration", "ExportNamedDeclaration"], "export"),
  var: newKeywordTester("VariableDeclaration", "var"),
  let: newKeywordTester("VariableDeclaration", "let"),
  const: newKeywordTester("VariableDeclaration", "const"),
  using: {
    test: (node) => node.type === "VariableDeclaration" && (node.kind === "using" || node.kind === "await using"),
  },
  type: newKeywordTester("TSTypeAliasDeclaration", "type"),
} satisfies Record<string, NodeTestObject>

const lineModeStatementTypes = Object.entries(maybeMultilineStatementTypes).flatMap(
  ([key, value]): (readonly [string, NodeTestObject])[] => {
    const singleline: NodeTestObject = {
      test: (node, sourceCode) => value.test(node, sourceCode) && isSingleLine(node),
    }

    const multiline: NodeTestObject = {
      test: (node, sourceCode) => value.test(node, sourceCode) && !isSingleLine(node),
    }

    return [
      [key, value],
      [`singleline-${key}`, singleline],
      [`multiline-${key}`, multiline],
    ]
  },
)

const fixedStatementTypes = {
  "*": { test: (): boolean => true },
  exports: { test: isCJSExport },
  require: { test: isCJSRequire },
  directive: { test: isDirective },
  iife: { test: isIIFEStatement },

  block: newNodeTypeTester("BlockStatement"),
  empty: newNodeTypeTester("EmptyStatement"),
  function: newNodeTypeTester("FunctionDeclaration"),
  "ts-method": newNodeTypeTester("TSMethodSignature"),

  break: newKeywordTester("BreakStatement", "break"),
  case: newKeywordTester("SwitchCase", "case"),
  class: newKeywordTester("ClassDeclaration", "class"),
  continue: newKeywordTester("ContinueStatement", "continue"),
  debugger: newKeywordTester("DebuggerStatement", "debugger"),
  default: newKeywordTester(["SwitchCase", "ExportDefaultDeclaration"], "default"),
  do: newKeywordTester("DoWhileStatement", "do"),
  for: newKeywordTester(["ForStatement", "ForInStatement", "ForOfStatement"], "for"),
  if: newKeywordTester("IfStatement", "if"),
  import: newKeywordTester("ImportDeclaration", "import"),
  switch: newKeywordTester("SwitchStatement", "switch"),
  throw: newKeywordTester("ThrowStatement", "throw"),
  try: newKeywordTester("TryStatement", "try"),
  while: newKeywordTester(["WhileStatement", "DoWhileStatement"], "while"),
  with: newKeywordTester("WithStatement", "with"),

  "cjs-export": {
    test: (node, sourceCode) =>
      node.type === "ExpressionStatement" &&
      node.expression.type === "AssignmentExpression" &&
      CJS_EXPORT.test(sourceCode.getText(node.expression.left)),
  },
  "cjs-import": {
    test: (node, sourceCode) => {
      if (node.type !== "VariableDeclaration") return false
      const init = node.declarations[0]?.init ?? null

      return init !== null && CJS_IMPORT.test(sourceCode.getText(init))
    },
  },

  enum: newKeywordTester("TSEnumDeclaration", "enum"),
  interface: newKeywordTester("TSInterfaceDeclaration", "interface"),
  "function-overload": newNodeTypeTester("TSDeclareFunction"),
} satisfies Record<string, NodeTestObject>

export const statementTypes = new Map<string, NodeTestObject>([
  ...Object.entries(fixedStatementTypes),
  ...lineModeStatementTypes,
])
