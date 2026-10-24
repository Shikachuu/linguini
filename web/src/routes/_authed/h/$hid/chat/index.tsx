import { createFileRoute } from "@tanstack/react-router"
import { NewChatButton } from "@/components/chat/thread-list"

const NoThread = () => {
  const { hid } = Route.useParams()

  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center text-sm text-muted-foreground">
      <p>Pick a chat or start a new one.</p>
      <NewChatButton hid={hid} />
    </div>
  )
}

export const Route = createFileRoute("/_authed/h/$hid/chat/")({
  component: NoThread,
})
