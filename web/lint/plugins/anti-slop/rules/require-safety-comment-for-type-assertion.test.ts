import { tester } from "../../rule-tester.ts"

import { requireSafetyCommentForTypeAssertionRule } from "./require-safety-comment-for-type-assertion.ts"

const error = { messageId: "missingSafetyComment" }

tester.run("anti-slop/require-safety-comment-for-type-assertion", requireSafetyCommentForTypeAssertionRule, {
  valid: [
    "const values = [1, 2] as const;",
    "const value = <const>{ id: 'one' };",
    "// SAFETY: The parser established the UserId invariant.\nconst id = value as UserId;",
    "function parse(): UserId {\n// SAFETY: Validation above established the UserId invariant.\nreturn value as UserId;\n}",
    "const id = /* SAFETY: Validation established the invariant. */ value as UserId;",
    "// SAFETY: The parser established the exported UserId invariant.\nexport const id = value as UserId;",
    "/* SAFETY:\n * The parser established the exported UserId invariant.\n */\nexport const id = value as UserId;",
    "class User {\n// SAFETY: The constructor input was parsed.\nid = value as UserId;\n}",
    "// SAFETY: Callers only reject with Error instances.\nthrow value as Error;",
  ],
  invalid: [
    { code: "const id = value as UserId;", errors: [error] },
    { code: "const id = <UserId>value;", errors: [error] },
    { code: "const id = value as UserId; // SAFETY: Too late.", errors: [error] },
    {
      code: "// This cast seems fine.\nconst id = value as UserId;",
      errors: [error],
    },
    { code: "// SAFETY:\nconst id = value as UserId;", errors: [error] },
    { code: "// INVARIANT: The caller parsed this value.\nconst id = value as UserId;", errors: [error] },
    { code: "// SAFETY:   \nconst id = value as UserId;", errors: [error] },
    { code: "const id = /* SAFETY: */ value as UserId;", errors: [error] },
    { code: "export const id = value as UserId;", errors: [error] },
    { code: "class User {\nid = value as UserId;\n}", errors: [error] },
    { code: "throw value as Error;", errors: [error] },
    {
      code: "// This is not a safety justification.\nexport const id = value as UserId;",
      errors: [error],
    },
  ],
})
