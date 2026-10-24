import type { UIMessage } from "ai"
import { describe, expect, it } from "vite-plus/test"
import { changeLines, chatErrorMessage, chatRequestBody, mergeAssistantMessages, threadMessages } from "./chat"

const user = (id: string, text: string): UIMessage => ({
  id,
  role: "user",
  parts: [{ type: "text", text }],
})

const assistant = (id: string, text: string): UIMessage => ({
  id,
  role: "assistant",
  parts: [{ type: "text", text, state: "done" }],
})

describe("chatRequestBody", () => {
  it("sends only the newest message with plain text parts", () => {
    const newest: UIMessage = {
      id: "m3",
      role: "user",
      metadata: { extra: true },
      parts: [
        { type: "text", text: "add rice", state: "done" },
        { type: "file", mediaType: "image/png", url: "data:," },
      ],
    }

    expect(chatRequestBody("t1", [user("m1", "hi"), assistant("m2", "hello"), newest])).toEqual({
      id: "t1",
      trigger: "submit-message",
      messages: [{ id: "m3", role: "user", parts: [{ type: "text", text: "add rice" }] }],
    })
  })
})

describe("mergeAssistantMessages", () => {
  it("joins consecutive assistant messages into one", () => {
    const merged = mergeAssistantMessages([
      user("u1", "q"),
      assistant("a1", "x"),
      assistant("a2", "y"),
      user("u2", "r"),
    ])

    expect(merged.map((m) => m.id)).toEqual(["u1", "a1", "u2"])
    expect(merged[1]?.parts).toHaveLength(2)
  })
})

describe("chatErrorMessage", () => {
  it("reads the FastAPI detail of a failed chat request", () => {
    expect(chatErrorMessage(new Error('{"detail":"This thread is already answering"}'))).toBe(
      "This thread is already answering",
    )
  })

  it("falls back to the raw message", () => {
    expect(chatErrorMessage(new Error("Failed to fetch"))).toBe("Failed to fetch")
  })
})

describe("changeLines", () => {
  it("reads batch results and single results", () => {
    const line = { ok: true, message: "rizs: 0 kg -> 1 kg", event_id: "e1" }
    expect(changeLines.safeParse({ results: [line], skipped_duplicate_order: false }).data).toEqual([line])
    expect(changeLines.safeParse(line).data).toEqual([line])
    expect(changeLines.safeParse("Removed rizs.").data).toBeUndefined()
    expect(changeLines.safeParse({ undone: 2, events: [] }).data).toBeUndefined()
  })
})

describe("chatErrorMessage with odd bodies", () => {
  it("tolerates non-object entries in a detail list", () => {
    expect(chatErrorMessage(new Error('{"detail":[null,"x",{"msg":"bad"}]}'))).toBe('null; "x"; bad')
  })
})

describe("threadMessages", () => {
  it("accepts a thread without messages", async () => {
    await expect(threadMessages([])).resolves.toEqual([])
  })

  it("parses stored messages and merges assistant turns", async () => {
    const messages = await threadMessages([
      { id: "u1", role: "user", parts: [{ type: "text", text: "q" }] },
      { id: "a1", role: "assistant", parts: [{ type: "text", text: "x" }] },
      { id: "a2", role: "assistant", parts: [{ type: "text", text: "y" }] },
    ])

    expect(messages.map((m) => m.id)).toEqual(["u1", "a1"])
    expect(messages[1]?.parts).toHaveLength(2)
  })

  it("accepts a stored tool call whose output is null", async () => {
    const [message] = await threadMessages([
      {
        id: "a1",
        role: "assistant",
        parts: [{ type: "tool-list_items", toolCallId: "c1", state: "output-available", input: {}, output: null }],
      },
    ])

    expect(message?.parts).toHaveLength(1)
  })

  it("rejects messages that are not UI messages", async () => {
    await expect(threadMessages([{ id: "u1", role: "robot", parts: [] }])).rejects.toThrow("Type validation failed")
  })
})
