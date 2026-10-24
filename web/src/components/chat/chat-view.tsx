import { useChat } from "@ai-sdk/react"
import { useQueryClient } from "@tanstack/react-query"
import { DefaultChatTransport, isToolUIPart, type UIMessage } from "ai"
import { useMemo } from "react"
import { toast } from "sonner"
import { apiHeaders } from "@/api/fetcher"
import { getGetThreadQueryKey, getListThreadsQueryKey } from "@/api/gen/endpoints/chat/chat"
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation"
import { Message, MessageContent, MessageResponse } from "@/components/ai-elements/message"
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
} from "@/components/ai-elements/prompt-input"
import { ToolPart } from "@/components/chat/tool-part"
import { chatErrorMessage, chatRequestBody, keyedParts } from "@/lib/chat"
import { invalidatePantry } from "@/lib/pantry"
import { invalidateRecipes } from "@/lib/recipes"

type ChatViewProps = {
  hid: string
  tid: string
  initialMessages: UIMessage[]
}

const chatTransport = (hid: string, tid: string) => {
  return new DefaultChatTransport({
    api: `/api/households/${hid}/threads/${tid}/chat`,
    headers: () => Object.fromEntries(apiHeaders("POST")),
    credentials: "same-origin",
    prepareSendMessagesRequest: ({ id, messages }) => ({ body: chatRequestBody(id, messages) }),
  })
}

export const ChatView = ({ hid, tid, initialMessages }: ChatViewProps) => {
  const queryClient = useQueryClient()
  const transport = useMemo(() => chatTransport(hid, tid), [hid, tid])

  const { messages, sendMessage, status, stop } = useChat({
    id: tid,
    messages: initialMessages,
    transport,
    onFinish: () => {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: getListThreadsQueryKey(hid) }),
        queryClient.invalidateQueries({ queryKey: getGetThreadQueryKey(hid, tid) }),
        invalidatePantry(queryClient, hid),
        invalidateRecipes(queryClient, hid),
      ])
    },
    onError: (error) => {
      toast.error(chatErrorMessage(error))
    },
  })

  const busy = status === "submitted" || status === "streaming"

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Conversation>
        <ConversationContent className="mx-auto w-full max-w-3xl gap-4">
          {messages.length === 0 ? (
            <ConversationEmptyState
              title="What's cooking?"
              description="Tell me what you bought or used, ask what to cook, or ask me to check Kifli."
            />
          ) : (
            messages.map((message) => (
              <Message key={message.id} from={message.role}>
                <MessageContent>
                  {keyedParts(message).map(({ key, part }) => {
                    if (part.type === "text") {
                      return message.role === "assistant" ? (
                        <MessageResponse key={key}>{part.text}</MessageResponse>
                      ) : (
                        <p key={key} className="whitespace-pre-wrap">
                          {part.text}
                        </p>
                      )
                    }

                    if (isToolUIPart(part)) {
                      return <ToolPart key={key} hid={hid} part={part} />
                    }

                    return null
                  })}
                </MessageContent>
              </Message>
            ))
          )}
          {status === "submitted" && <p className="text-sm text-muted-foreground">Thinking...</p>}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>
      <div className="mx-auto w-full max-w-3xl p-3">
        <PromptInput
          onSubmit={({ text }) => {
            if (text.trim() && !busy) void sendMessage({ text: text.trim() })
          }}
        >
          <PromptInputBody>
            <PromptInputTextarea placeholder="Message the kitchen" />
          </PromptInputBody>
          <PromptInputFooter className="justify-end">
            <PromptInputSubmit
              status={status}
              onStop={() => {
                void stop()
              }}
            />
          </PromptInputFooter>
        </PromptInput>
      </div>
    </div>
  )
}
