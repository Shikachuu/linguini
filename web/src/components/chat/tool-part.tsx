import { getToolName, type DynamicToolUIPart, type ToolUIPart } from "ai"
import { CheckIcon, XIcon } from "lucide-react"
import { Tool, ToolContent, ToolHeader, ToolInput, ToolOutput } from "@/components/ai-elements/tool"
import { UndoButton } from "@/components/undo-button"
import { changeLines, toolTitle } from "@/lib/chat"

export const ToolPart = ({ hid, part }: { hid: string; part: ToolUIPart | DynamicToolUIPart }) => {
  const name = getToolName(part)
  const lines = part.state === "output-available" ? changeLines.safeParse(part.output).data : undefined

  return (
    <Tool className="mb-0">
      {part.type === "dynamic-tool" ? (
        <ToolHeader title={toolTitle(name)} type={part.type} state={part.state} toolName={part.toolName} />
      ) : (
        <ToolHeader title={toolTitle(name)} type={part.type} state={part.state} />
      )}
      {lines && (
        <ul aria-label={toolTitle(name)} className="grid gap-1.5 px-3 pb-3 text-sm">
          {lines.map((line, index) => (
            <li key={line.event_id ?? index} className="flex items-center gap-2">
              {line.ok ? (
                <CheckIcon className="size-4 shrink-0 text-green-600" aria-label="done" />
              ) : (
                <XIcon className="size-4 shrink-0 text-destructive" aria-label="failed" />
              )}
              <span className="min-w-0 flex-1">{line.message}</span>
              {line.event_id !== null && <UndoButton hid={hid} eventId={line.event_id} />}
            </li>
          ))}
        </ul>
      )}
      <ToolContent>
        <ToolInput input={part.input} />
        <ToolOutput output={part.output} errorText={part.errorText} />
      </ToolContent>
    </Tool>
  )
}
