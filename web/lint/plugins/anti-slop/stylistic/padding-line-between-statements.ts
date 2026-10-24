// Adapted from ESLint Stylistic padding-line-between-statements (MIT), see the lint-config README.
import type {
  ESTree,
  Context as RuleContext,
  SourceCode,
  Token as SyntaxToken,
  Comment,
  CreateRule,
  Location,
  RuleOptionsSchema,
} from "vite-plus/lint/plugins"

import { isSemicolonToken, isSingleLine, isTokenOnSameLine, LINEBREAKS } from "./padding-line-ast.ts"
import { statementTypes } from "./padding-line-statement-types.ts"

import type { RuleOptions, SelectorOption, StatementOption } from "./padding-line-options.ts"

type Token = SyntaxToken | Comment

type PaddingLines = [Token, Token][]

type MatchState = {
  readonly options: RuleOptions
  readonly selectorMatchedNodes: ReadonlyMap<string, ReadonlySet<ESTree.Node>>
  readonly sourceCode: SourceCode
}

const LT = `[${Array.from(LINEBREAKS).join("")}]`

const PADDING_LINE_SEQUENCE = new RegExp(String.raw`^(\s*?${LT})\s*${LT}(\s*;?)$`, "u")

const PADDED_PARENT_TYPES = new Set([
  "BlockStatement",
  "Program",
  "StaticBlock",
  "SwitchCase",
  "SwitchStatement",
  "TSInterfaceBody",
  "TSModuleBlock",
  "TSTypeLiteral",
])

const isSelectorOption = (option: StatementOption): option is SelectorOption => {
  return !Array.isArray(option) && option instanceof Object
}

const getActualLastToken = (node: ESTree.Node, sourceCode: SourceCode): Token => {
  const semiToken = sourceCode.getLastToken(node)

  if (semiToken === null) throw new Error("Padding rule invariant: statement has no tokens")
  const prevToken = sourceCode.getTokenBefore(semiToken)
  const nextToken = sourceCode.getTokenAfter(semiToken)

  const isSemicolonLessStyle =
    prevToken !== null &&
    nextToken !== null &&
    prevToken.range[0] >= node.range[0] &&
    isSemicolonToken(semiToken) &&
    !isTokenOnSameLine(prevToken, semiToken) &&
    isTokenOnSameLine(semiToken, nextToken)

  return isSemicolonLessStyle ? prevToken : semiToken
}

const replacerToRemovePaddingLines = (_: string, trailingSpaces: string, indentSpaces: string): string => {
  return trailingSpaces + indentSpaces
}

const getReportLoc = (node: ESTree.Node, sourceCode: SourceCode): Location => {
  if (isSingleLine(node)) return node.loc
  const line = node.loc.start.line
  const sourceLine = sourceCode.lines[line - 1]

  if (sourceLine === undefined) throw new Error("Padding rule invariant: statement source line is missing")

  return {
    start: node.loc.start,
    end: { line, column: sourceLine.length },
  }
}

const allowAnyPadding = (): void => {}

const verifyForNever = (
  context: RuleContext,
  _: ESTree.Node,
  nextNode: ESTree.Node,
  paddingLines: PaddingLines,
): void => {
  if (paddingLines.length === 0) return

  context.report({
    node: nextNode,
    messageId: "unexpectedBlankLine",
    loc: getReportLoc(nextNode, context.sourceCode),
    fix(fixer) {
      if (paddingLines.length >= 2) return null
      const paddingPair = paddingLines[0]

      if (paddingPair === undefined) throw new Error("Padding rule invariant: reported padding pair is missing")
      const [prevToken, nextToken] = paddingPair
      const start = prevToken.range[1]
      const end = nextToken.range[0]

      const text = context.sourceCode.text
        .slice(start, end)
        .replace(PADDING_LINE_SEQUENCE, replacerToRemovePaddingLines)

      return fixer.replaceTextRange([start, end], text)
    },
  })
}

const verifyForAlways = (
  context: RuleContext,
  prevNode: ESTree.Node,
  nextNode: ESTree.Node,
  paddingLines: PaddingLines,
): void => {
  if (paddingLines.length > 0) return

  context.report({
    node: nextNode,
    messageId: "expectedBlankLine",
    loc: getReportLoc(nextNode, context.sourceCode),
    fix(fixer) {
      const sourceCode = context.sourceCode
      let prevToken = getActualLastToken(prevNode, sourceCode)

      const nextToken =
        sourceCode.getFirstTokenBetween(prevToken, nextNode, {
          includeComments: true,
          filter(token) {
            if (isTokenOnSameLine(prevToken, token)) {
              prevToken = token

              return false
            }

            return true
          },
        }) ?? nextNode

      const insertText = isTokenOnSameLine(prevToken, nextToken) ? "\n\n" : "\n"

      return fixer.insertTextAfter(prevToken, insertText)
    },
  })
}

const PaddingTypes = {
  any: { verify: allowAnyPadding },
  never: { verify: verifyForNever },
  always: { verify: verifyForAlways },
}

const schema = {
  $defs: {
    paddingType: { type: "string", enum: Object.keys(PaddingTypes) },
    statementType: { type: "string", enum: [...statementTypes.keys()] },
    selectorOption: {
      type: "object",
      properties: {
        selector: { type: "string" },
        lineMode: { type: "string", enum: ["any", "singleline", "multiline"] },
      },
      required: ["selector"],
      additionalProperties: false,
    },
    statementMatcher: {
      anyOf: [{ $ref: "#/$defs/statementType" }, { $ref: "#/$defs/selectorOption" }],
    },
    statementOption: {
      anyOf: [
        { $ref: "#/$defs/statementMatcher" },
        {
          type: "array",
          items: { $ref: "#/$defs/statementMatcher" },
          minItems: 1,
          uniqueItems: true,
          additionalItems: false,
        },
      ],
    },
  },
  type: "array",
  additionalItems: false,
  items: {
    type: "object",
    properties: {
      blankLine: { $ref: "#/$defs/paddingType" },
      prev: { $ref: "#/$defs/statementOption" },
      next: { $ref: "#/$defs/statementOption" },
    },
    additionalProperties: false,
    required: ["blankLine", "prev", "next"],
  },
} satisfies RuleOptionsSchema

const selectorsOf = (option: StatementOption): string[] => {
  return [option].flat().flatMap((matcher) => (isSelectorOption(matcher) ? [matcher.selector] : []))
}

const matchStatement = (state: MatchState, node: ESTree.Node, type: StatementOption): boolean => {
  let innerStatementNode = node

  while (innerStatementNode.type === "LabeledStatement") innerStatementNode = innerStatementNode.body

  if (Array.isArray(type)) return type.some((matcher) => matchStatement(state, innerStatementNode, matcher))

  if (!isSelectorOption(type)) {
    const statementType = statementTypes.get(type)

    if (statementType === undefined) throw new Error(`Padding rule invariant: unsupported statement type ${type}`)

    return statementType.test(innerStatementNode, state.sourceCode)
  }

  if (state.selectorMatchedNodes.get(type.selector)?.has(innerStatementNode) !== true) return false

  if (type.lineMode === "singleline") return isSingleLine(innerStatementNode)

  if (type.lineMode === "multiline") return !isSingleLine(innerStatementNode)

  return true
}

const getPaddingType = (
  state: MatchState,
  prevNode: ESTree.Node,
  nextNode: ESTree.Node,
): (typeof PaddingTypes)[keyof typeof PaddingTypes] => {
  const configure = state.options.findLast(
    (entry) => matchStatement(state, prevNode, entry.prev) && matchStatement(state, nextNode, entry.next),
  )

  return configure === undefined ? PaddingTypes.any : PaddingTypes[configure.blankLine]
}

const getPaddingLineSequences = (
  sourceCode: SourceCode,
  prevNode: ESTree.Node,
  nextNode: ESTree.Node,
): PaddingLines => {
  const pairs: PaddingLines = []
  let prevToken = getActualLastToken(prevNode, sourceCode)

  if (nextNode.loc.start.line - prevToken.loc.end.line < 2) return pairs

  do {
    const token = sourceCode.getTokenAfter(prevToken, { includeComments: true })

    if (token === null) break

    if (token.loc.start.line - prevToken.loc.end.line >= 2) pairs.push([prevToken, token])
    prevToken = token
  } while (prevToken.range[0] < nextNode.range[0])

  return pairs
}

export const createPaddingLineRule = (options: RuleOptions): CreateRule => {
  return {
    meta: {
      type: "layout",
      docs: { description: "Require or disallow padding lines between statements" },
      fixable: "whitespace",
      hasSuggestions: false,
      schema,
      messages: {
        unexpectedBlankLine: "Unexpected blank line before this statement.",
        expectedBlankLine: "Expected blank line before this statement.",
      },
    },
    create(context) {
      const selectors = options.flatMap((entry) => [...selectorsOf(entry.prev), ...selectorsOf(entry.next)])
      const selectorMatchedNodes = new Map(selectors.map((selector) => [selector, new Set<ESTree.Node>()]))
      const state: MatchState = { options, selectorMatchedNodes, sourceCode: context.sourceCode }
      const pendingPairs: { prevNode: ESTree.Node; nextNode: ESTree.Node }[] = []
      const scopes: { prevNode: ESTree.Node | null }[] = []

      const enterScope = (): void => {
        scopes.push({ prevNode: null })
      }

      const exitScope = (): void => {
        scopes.pop()
      }

      const verify = (node: ESTree.Node): void => {
        const scope = scopes.at(-1)

        if (scope === undefined || !PADDED_PARENT_TYPES.has(node.parent?.type ?? "")) return

        if (scope.prevNode !== null) pendingPairs.push({ prevNode: scope.prevNode, nextNode: node })
        scope.prevNode = node
      }

      const verifyThenEnterScope = (node: ESTree.Node): void => {
        verify(node)
        enterScope()
      }

      const selectorMatchListeners = Object.fromEntries(
        Array.from(selectorMatchedNodes, ([selector, nodes]) => [
          selector,
          (node: ESTree.Node): void => {
            nodes.add(node)
          },
        ]),
      )

      return {
        Program: enterScope,
        "Program:exit": () => {
          for (const { prevNode, nextNode } of pendingPairs) {
            const paddingLines = getPaddingLineSequences(context.sourceCode, prevNode, nextNode)
            getPaddingType(state, prevNode, nextNode).verify(context, prevNode, nextNode, paddingLines)
          }

          exitScope()
        },
        BlockStatement: enterScope,
        "BlockStatement:exit": exitScope,
        SwitchStatement: enterScope,
        "SwitchStatement:exit": exitScope,
        SwitchCase: verifyThenEnterScope,
        "SwitchCase:exit": exitScope,
        StaticBlock: enterScope,
        "StaticBlock:exit": exitScope,
        TSInterfaceBody: enterScope,
        "TSInterfaceBody:exit": exitScope,
        TSModuleBlock: enterScope,
        "TSModuleBlock:exit": exitScope,
        TSTypeLiteral: enterScope,
        "TSTypeLiteral:exit": exitScope,
        TSDeclareFunction: verifyThenEnterScope,
        "TSDeclareFunction:exit": exitScope,
        TSMethodSignature: verifyThenEnterScope,
        "TSMethodSignature:exit": exitScope,
        ":statement": verify,
        ...selectorMatchListeners,
      }
    },
  }
}
