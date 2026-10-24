import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vite-plus/test"
import { ChatView } from "@/components/chat/chat-view"
import { Toaster } from "@/components/ui/sonner"
import { renderWithClient } from "@/test/render"
import { server } from "@/test/server"

const CHAT_URL = "*/api/households/h1/threads/t1/chat"

function sse(...chunks: object[]): Response {
  const body = [...chunks.map((c) => `data: ${JSON.stringify(c)}\n\n`), "data: [DONE]\n\n"].join("")
  return new HttpResponse(body, {
    headers: { "content-type": "text/event-stream", "x-vercel-ai-ui-message-stream": "v1" },
  })
}

describe("ChatView", () => {
  it("posts the newest message with the CSRF header and renders the streamed reply", async () => {
    let request: { headers: Headers; body: unknown } | undefined
    server.use(
      http.post(CHAT_URL, async ({ request: r }) => {
        request = { headers: r.headers, body: await r.json() }
        return sse(
          { type: "start" },
          { type: "text-start", id: "x" },
          { type: "text-delta", id: "x", delta: "Added rice." },
          { type: "text-end", id: "x" },
          { type: "finish" },
        )
      }),
    )
    renderWithClient(<ChatView hid="h1" tid="t1" initialMessages={[]} />)
    await userEvent.type(screen.getByPlaceholderText("Message the kitchen"), "add rice{Enter}")
    expect(await screen.findByText("Added rice.")).toBeInTheDocument()
    expect(request?.headers.get("x-requested-with")).toBe("linguini")
    expect(request?.body).toMatchObject({
      trigger: "submit-message",
      messages: [{ role: "user", parts: [{ type: "text", text: "add rice" }] }],
    })
  })

  it("shows the server's reason when the thread is busy", async () => {
    server.use(
      http.post(CHAT_URL, () => HttpResponse.json({ detail: "This thread is already answering" }, { status: 409 })),
    )
    renderWithClient(
      <>
        <ChatView hid="h1" tid="t1" initialMessages={[]} />
        <Toaster />
      </>,
    )
    await userEvent.type(screen.getByPlaceholderText("Message the kitchen"), "hello{Enter}")
    await waitFor(() => expect(screen.getByText("This thread is already answering")).toBeInTheDocument())
  })
})
