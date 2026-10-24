import { createFileRoute, Outlet, useParams } from "@tanstack/react-router"
import { ThreadList } from "@/components/chat/thread-list"
import { cn } from "@/lib/utils"

const ChatLayout = () => {
  const { hid } = Route.useParams()
  const { tid } = useParams({ strict: false })

  return (
    <div className="flex h-full min-h-0">
      <aside className={cn("w-full overflow-y-auto md:w-72 md:shrink-0 md:border-r", tid && "hidden md:block")}>
        <ThreadList hid={hid} activeId={tid} />
      </aside>
      <section className={cn("min-h-0 min-w-0 flex-1", !tid && "hidden md:block")}>
        <Outlet />
      </section>
    </div>
  )
}

export const Route = createFileRoute("/_authed/h/$hid/chat")({
  component: ChatLayout,
})
