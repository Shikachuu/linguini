import { defineRule } from "vite-plus/lint/plugins"

import type { ESTree, SourceCode } from "vite-plus/lint/plugins"

type TypeAssertion = ESTree.TSAsExpression | ESTree.TSTypeAssertion

const safetyCommentPattern = /(?:^|[^\p{L}\p{N}_])SAFETY\s*:\s*\S/u

const commentOwnerKinds = new Set([
  "ExpressionStatement",
  "PropertyDefinition",
  "ReturnStatement",
  "ThrowStatement",
  "VariableDeclaration",
])

const isConstAssertion = (node: TypeAssertion): boolean => {
  return (
    node.typeAnnotation.type === "TSTypeReference" &&
    node.typeAnnotation.typeName.type === "Identifier" &&
    node.typeAnnotation.typeName.name === "const"
  )
}

const hasSafetyJustificationBefore = (
  sourceCode: SourceCode,
  owner: ESTree.Node,
  assertion: TypeAssertion,
): boolean => {
  return sourceCode
    .getCommentsBefore(owner)
    .some((comment) => comment.end <= assertion.start && safetyCommentPattern.test(comment.value))
}

const hasSafetyComment = (sourceCode: SourceCode, node: TypeAssertion): boolean => {
  let current: ESTree.Node = node

  while (true) {
    if (hasSafetyJustificationBefore(sourceCode, current, node)) return true

    if (commentOwnerKinds.has(current.type)) {
      const exportDeclaration = current.parent

      return (
        exportDeclaration.type === "ExportNamedDeclaration" &&
        exportDeclaration.declaration === current &&
        hasSafetyJustificationBefore(sourceCode, exportDeclaration, node)
      )
    }

    if (current.parent.type === "Program") return false
    current = current.parent
  }
}

export const requireSafetyCommentForTypeAssertionRule = defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Require a nearby SAFETY comment for every TypeScript type assertion except const assertions.",
    },
    messages: {
      missingSafetyComment:
        "This type assertion has no `SAFETY:` justification. State the checked invariant immediately before the assertion or its containing statement.",
    },
    schema: [],
  },
  createOnce(context) {
    const checkAssertion = (node: TypeAssertion) => {
      if (isConstAssertion(node) || hasSafetyComment(context.sourceCode, node)) return
      context.report({ node, messageId: "missingSafetyComment" })
    }

    return {
      TSAsExpression: checkAssertion,
      TSTypeAssertion: checkAssertion,
    }
  },
})
