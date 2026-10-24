import { useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { MoreHorizontalIcon, PlusIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import {
  getListThreadsQueryKey,
  useCreateThread,
  useDeleteThread,
  useListThreads,
  useRenameThread,
} from "@/api/gen/endpoints/chat/chat"
import type { ThreadOut } from "@/api/gen/model"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { errorMessage } from "@/lib/errors"
import { formatDateTime } from "@/lib/format"

export const NewChatButton = ({ hid }: { hid: string }) => {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const create = useCreateThread({
    mutation: {
      onSuccess: async (thread) => {
        await queryClient.invalidateQueries({ queryKey: getListThreadsQueryKey(hid) })
        await navigate({ to: "/h/$hid/chat/$tid", params: { hid, tid: thread.id } })
      },
      onError: (error) => toast.error(errorMessage(error)),
    },
  })

  return (
    <Button
      size="sm"
      disabled={create.isPending}
      onClick={() => {
        create.mutate({ householdId: hid, data: {} })
      }}
    >
      <PlusIcon /> New chat
    </Button>
  )
}

export const ThreadList = ({ hid, activeId }: { hid: string; activeId?: string }) => {
  const threads = useListThreads(hid)

  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between gap-2 px-4 pt-4 pb-2">
        <h1 className="text-xl font-semibold">Chats</h1>
        <NewChatButton hid={hid} />
      </div>
      {threads.isPending && <Skeleton className="mx-4 h-10" />}
      {threads.isError && <p className="px-4 text-sm text-destructive">{errorMessage(threads.error)}</p>}
      {threads.data?.length === 0 && <p className="px-4 text-sm text-muted-foreground">No chats yet.</p>}
      <ul>
        {threads.data?.map((thread) => (
          <ThreadRow key={thread.id} hid={hid} thread={thread} active={thread.id === activeId} />
        ))}
      </ul>
    </div>
  )
}

type ThreadDialogProps = {
  hid: string
  thread: ThreadOut
  open: boolean
  onOpenChange: (open: boolean) => void
}

const useRefreshThreads = (hid: string) => {
  const queryClient = useQueryClient()

  return () => queryClient.invalidateQueries({ queryKey: getListThreadsQueryKey(hid) })
}

const RenameThreadDialog = ({
  hid,
  thread,
  open,
  onOpenChange,
  title,
  onTitleChange,
}: ThreadDialogProps & { title: string; onTitleChange: (title: string) => void }) => {
  const refresh = useRefreshThreads(hid)

  const rename = useRenameThread({
    mutation: {
      onSuccess: async () => {
        await refresh()
        onOpenChange(false)
      },
    },
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rename chat</DialogTitle>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            rename.mutate({
              householdId: hid,
              threadId: thread.id,
              data: { title: title.trim() },
            })
          }}
        >
          <Input
            aria-label="Title"
            value={title}
            onChange={(e) => {
              onTitleChange(e.target.value)
            }}
            maxLength={80}
            required
          />
          {rename.isError && <p className="text-sm text-destructive">{errorMessage(rename.error)}</p>}
          <DialogFooter>
            <Button type="submit" disabled={rename.isPending}>
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

const DeleteThreadDialog = ({ hid, thread, open, onOpenChange, active }: ThreadDialogProps & { active: boolean }) => {
  const refresh = useRefreshThreads(hid)
  const navigate = useNavigate()

  const remove = useDeleteThread({
    mutation: {
      onSuccess: async () => {
        await refresh()

        if (active) await navigate({ to: "/h/$hid/chat", params: { hid } })
      },
      onError: (error) => toast.error(errorMessage(error)),
    },
  })

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {thread.title}?</AlertDialogTitle>
          <AlertDialogDescription>
            The conversation is deleted for everyone. Pantry changes it made stay.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            onClick={() => {
              remove.mutate({ householdId: hid, threadId: thread.id })
            }}
          >
            Delete
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

const ThreadRow = ({ hid, thread, active }: { hid: string; thread: ThreadOut; active: boolean }) => {
  const [dialog, setDialog] = useState<"rename" | "delete" | null>(null)
  const [title, setTitle] = useState(thread.title)

  return (
    <li className={active ? "flex items-center bg-accent" : "flex items-center hover:bg-accent/60"}>
      <Link to="/h/$hid/chat/$tid" params={{ hid, tid: thread.id }} className="min-w-0 flex-1 px-4 py-2.5">
        <div className="truncate text-sm">{thread.title}</div>
        <div className="text-xs text-muted-foreground">{formatDateTime(thread.updated_at)}</div>
      </Link>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label={`Actions for ${thread.title}`} className="mr-2">
            <MoreHorizontalIcon />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            onSelect={() => {
              setTitle(thread.title)
              setDialog("rename")
            }}
          >
            Rename
          </DropdownMenuItem>
          <DropdownMenuItem
            variant="destructive"
            onSelect={() => {
              setDialog("delete")
            }}
          >
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <RenameThreadDialog
        hid={hid}
        thread={thread}
        open={dialog === "rename"}
        onOpenChange={(open) => {
          setDialog(open ? "rename" : null)
        }}
        title={title}
        onTitleChange={setTitle}
      />
      <DeleteThreadDialog
        hid={hid}
        thread={thread}
        active={active}
        open={dialog === "delete"}
        onOpenChange={(open) => {
          setDialog(open ? "delete" : null)
        }}
      />
    </li>
  )
}
