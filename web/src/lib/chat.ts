import type { UIMessage } from "ai"
import { detailOf } from "@/api/fetcher"

export type ChangeLine = {
  ok: boolean
  message: string
  event_id: string | null
}

const TOOL_TITLES: Record<string, string> = {
  list_items: "Checked the pantry",
  search_items: "Searched the pantry",
  add_items: "Added to the pantry",
  consume_items: "Used from the pantry",
  set_item: "Updated the pantry",
  remove_item: "Removed from the pantry",
  undo: "Undid changes",
  list_recipes: "Looked up recipes",
  get_recipe: "Read a recipe",
  save_recipe: "Saved a recipe",
  cook_recipe: "Cooked a recipe",
}

export const toolTitle = (name: string): string => {
  return TOOL_TITLES[name] ?? name.replaceAll("_", " ")
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

const parseJson = (text: string): unknown => {
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

export const chatErrorMessage = (error: Error): string => {
  return detailOf(parseJson(error.message)) ?? (error.message || "The reply failed.")
}

const isChangeLine = (value: unknown): value is ChangeLine => {
  return (
    typeof value === "object" &&
    value !== null &&
    "ok" in value &&
    typeof value.ok === "boolean" &&
    "message" in value &&
    typeof value.message === "string"
  )
}

export const changeLines = (output: unknown): ChangeLine[] | null => {
  if (isChangeLine(output)) return [{ ...output, event_id: output.event_id ?? null }]

  if (typeof output === "object" && output !== null && "results" in output && Array.isArray(output.results)) {
    const lines = output.results.filter(isChangeLine)

    return lines.length > 0 ? lines.map((l) => ({ ...l, event_id: l.event_id ?? null })) : null
  }

  return null
}
