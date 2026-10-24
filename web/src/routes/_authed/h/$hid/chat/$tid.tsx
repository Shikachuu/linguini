import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeftIcon, Undo2Icon } from "lucide-react"
import { toast } from "sonner"
import { getGetThreadQueryKey, getThread } from "@/api/gen/endpoints/chat/chat"
import { useUndoLastTurn } from "@/api/gen/endpoints/inventory/inventory"
import { ChatView } from "@/components/chat/chat-view"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { threadMessages } from "@/lib/chat"
import { errorMessage } from "@/lib/errors"
import { invalidatePantry } from "@/lib/pantry"

const useThread = (hid: string, tid: string) =>
  useQuery({
    queryKey: getGetThreadQueryKey(hid, tid),
    queryFn: async ({ signal }) => {
      const detail = await getThread(hid, tid, { signal })

      return { title: detail.title, messages: await threadMessages(detail.messages) }
    },
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })

const Thread = () => {
  const { hid, tid } = Route.useParams()
  const queryClient = useQueryClient()
  const thread = useThread(hid, tid)

  const undoTurn = useUndoLastTurn({
    mutation: {
      onSuccess: async (events) => {
        await invalidatePantry(queryClient, hid)
        toast.success(events.length > 0 ? `Undid ${events.length} pantry changes` : "Nothing to undo")
      },
      onError: (error) => toast.error(errorMessage(error)),
    },
  })

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-1 border-b px-2">
        <Button asChild variant="ghost" size="icon" aria-label="Back to chats" className="md:hidden">
          <Link to="/h/$hid/chat" params={{ hid }}>
            <ArrowLeftIcon />
          </Link>
        </Button>
        <h2 className="min-w-0 flex-1 truncate px-2 font-medium">{thread.data?.title}</h2>
        <Button
          variant="ghost"
          size="sm"
          disabled={undoTurn.isPending}
          onClick={() => {
            undoTurn.mutate({ householdId: hid, params: { thread_id: tid } })
          }}
        >
          <Undo2Icon /> Undo last turn
        </Button>
      </header>
      {thread.isPending && <Skeleton className="m-4 h-24" />}
      {thread.isError && <p className="p-4 text-sm text-destructive">{errorMessage(thread.error)}</p>}
      {thread.data && <ChatView key={tid} hid={hid} tid={tid} initialMessages={thread.data.messages} />}
    </div>
  )
}

export const Route = createFileRoute("/_authed/h/$hid/chat/$tid")({
  component: Thread,
})
