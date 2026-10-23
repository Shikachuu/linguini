import type { UIMessage } from "ai";
import { describe, expect, it } from "vite-plus/test";
import { changeLines, chatErrorMessage, chatRequestBody, mergeAssistantMessages } from "./chat";

const user = (id: string, text: string): UIMessage => ({
  id,
  role: "user",
  parts: [{ type: "text", text }],
});
const assistant = (id: string, text: string): UIMessage => ({
  id,
  role: "assistant",
  parts: [{ type: "text", text, state: "done" }],
});

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
    };
    expect(chatRequestBody("t1", [user("m1", "hi"), assistant("m2", "hello"), newest])).toEqual({
      id: "t1",
      trigger: "submit-message",
      messages: [{ id: "m3", role: "user", parts: [{ type: "text", text: "add rice" }] }],
    });
  });
});

describe("mergeAssistantMessages", () => {
  it("joins consecutive assistant messages into one", () => {
    const merged = mergeAssistantMessages([
      user("u1", "q"),
      assistant("a1", "x"),
      assistant("a2", "y"),
      user("u2", "r"),
    ]);
    expect(merged.map((m) => m.id)).toEqual(["u1", "a1", "u2"]);
    expect(merged[1]?.parts).toHaveLength(2);
  });
});

describe("chatErrorMessage", () => {
  it("reads the FastAPI detail of a failed chat request", () => {
    expect(chatErrorMessage(new Error('{"detail":"This thread is already answering"}'))).toBe(
      "This thread is already answering",
    );
  });

  it("falls back to the raw message", () => {
    expect(chatErrorMessage(new Error("Failed to fetch"))).toBe("Failed to fetch");
  });
});

describe("changeLines", () => {
  it("reads batch results and single results", () => {
    const line = { ok: true, message: "rizs: 0 kg -> 1 kg", event_id: "e1" };
    expect(changeLines({ results: [line], skipped_duplicate_order: false })).toEqual([line]);
    expect(changeLines(line)).toEqual([line]);
    expect(changeLines("Removed rizs.")).toBeNull();
    expect(changeLines({ undone: 2, events: [] })).toBeNull();
  });
});
