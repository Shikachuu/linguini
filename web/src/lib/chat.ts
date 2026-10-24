import { isToolUIPart, type UIMessage } from "ai"
import { z } from "zod"
import { detailOf } from "@/api/fetcher"

const changeLine = z.object({
  ok: z.boolean(),
  message: z.string(),
  event_id: z
    .string()
    .nullish()
    .transform((id) => id ?? null),
})

export const changeLines = z
  .union([
    changeLine.transform((line) => [line]),
    z
      .object({ results: z.array(z.unknown()) })
      .transform(({ results }) => results.flatMap((result) => changeLine.safeParse(result).data ?? [])),
  ])
  .refine((lines) => lines.length > 0)

const TOOL_TITLES = new Map([
  ["list_items", "Checked the pantry"],
  ["search_items", "Searched the pantry"],
  ["add_items", "Added to the pantry"],
  ["consume_items", "Used from the pantry"],
  ["set_item", "Updated the pantry"],
  ["remove_item", "Removed from the pantry"],
  ["undo", "Undid changes"],
  ["list_recipes", "Looked up recipes"],
  ["get_recipe", "Read a recipe"],
  ["save_recipe", "Saved a recipe"],
  ["cook_recipe", "Cooked a recipe"],
])

export const toolTitle = (name: string): string => {
  return TOOL_TITLES.get(name) ?? name.replaceAll("_", " ")
}

export const chatRequestBody = (id: string, messages: UIMessage[]) => {
  const last = messages.at(-1)
  const parts = (last?.parts ?? []).flatMap((part) => (part.type === "text" ? [{ type: "text", text: part.text }] : []))

  return {
    id,
    trigger: "submit-message",
    messages: last ? [{ id: last.id, role: last.role, parts }] : [],
  }
}

export const mergeAssistantMessages = (messages: UIMessage[]): UIMessage[] => {
  const merged: UIMessage[] = []

  for (const message of messages) {
    const previous = merged.at(-1)

    if (previous?.role === "assistant" && message.role === "assistant") {
      merged[merged.length - 1] = { ...previous, parts: [...previous.parts, ...message.parts] }
    } else {
      merged.push(message)
    }
  }

  return merged
}

export const chatErrorMessage = (error: Error): string => {
  return detailOf(error.message) ?? (error.message || "The reply failed.")
}

export const keyedParts = (message: UIMessage) => {
  return message.parts.map((part, position) => ({
    key: isToolUIPart(part) ? part.toolCallId : `${message.id}:${position}`,
    part,
  }))
}
