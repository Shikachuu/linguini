import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import type { UIMessage } from "ai";
import { ArrowLeftIcon, Undo2Icon } from "lucide-react";
import { toast } from "sonner";
import { useGetThread } from "@/api/gen/endpoints/chat/chat";
import { useUndoLastTurn } from "@/api/gen/endpoints/inventory/inventory";
import { ChatView } from "@/components/chat/chat-view";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { mergeAssistantMessages } from "@/lib/chat";
import { errorMessage } from "@/lib/errors";
import { invalidatePantry } from "@/lib/pantry";

export const Route = createFileRoute("/_authed/h/$hid/chat/$tid")({
  component: Thread,
});

function Thread() {
  const { hid, tid } = Route.useParams();
  const queryClient = useQueryClient();
  const thread = useGetThread(hid, tid, {
    query: { staleTime: Infinity, refetchOnWindowFocus: false },
  });
  const undoTurn = useUndoLastTurn({
    mutation: {
      onSuccess: async (events) => {
        await invalidatePantry(queryClient, hid);
        toast.success(events.length ? `Undid ${events.length} pantry changes` : "Nothing to undo");
      },
      onError: (error) => toast.error(errorMessage(error)),
    },
  });

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-1 border-b px-2">
        <Button
          asChild
          variant="ghost"
          size="icon"
          aria-label="Back to chats"
          className="md:hidden"
        >
          <Link to="/h/$hid/chat" params={{ hid }}>
            <ArrowLeftIcon />
          </Link>
        </Button>
        <h2 className="min-w-0 flex-1 truncate px-2 font-medium">{thread.data?.title}</h2>
        <Button
          variant="ghost"
          size="sm"
          disabled={undoTurn.isPending}
          onClick={() => undoTurn.mutate({ householdId: hid, params: { thread_id: tid } })}
        >
          <Undo2Icon /> Undo last turn
        </Button>
      </header>
      {thread.isPending && <Skeleton className="m-4 h-24" />}
      {thread.isError && (
        <p className="text-destructive p-4 text-sm">{errorMessage(thread.error)}</p>
      )}
      {thread.data && (
        <ChatView
          key={tid}
          hid={hid}
          tid={tid}
          initialMessages={mergeAssistantMessages(thread.data.messages as unknown as UIMessage[])}
        />
      )}
    </div>
  );
}
