import { useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { HistoryIcon, PencilIcon, PlusIcon, Trash2Icon } from "lucide-react"
import { useDeferredValue, useState } from "react"
import { useDeleteItem, useListItems } from "@/api/gen/endpoints/inventory/inventory"
import type { ItemOut } from "@/api/gen/model"
import { PageHeader } from "@/components/app-shell"
import { Confirm } from "@/components/confirm"
import { ItemDialog } from "@/components/pantry/item-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { errorMessage } from "@/lib/errors"
import { formatQuantity } from "@/lib/format"
import { freshness, invalidatePantry } from "@/lib/pantry"

const Pantry = () => {
  const { hid } = Route.useParams()
  const [search, setSearch] = useState("")
  const q = useDeferredValue(search.trim())
  const items = useListItems(hid, q ? { q } : undefined)

  return (
    <div className="mx-auto max-w-2xl pb-6">
      <PageHeader
        title="Pantry"
        actions={
          <>
            <Button asChild variant="ghost" size="icon" aria-label="History">
              <Link to="/h/$hid/inventory/events" params={{ hid }}>
                <HistoryIcon />
              </Link>
            </Button>
            <ItemDialog
              hid={hid}
              trigger={
                <Button size="sm">
                  <PlusIcon /> Add
                </Button>
              }
            />
          </>
        }
      />
      <div className="px-4 pb-3">
        <Input
          type="search"
          placeholder="Search the pantry"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
          }}
          maxLength={80}
        />
      </div>
      {items.isPending && <ListSkeleton />}
      {items.isError && <p className="px-4 text-sm text-destructive">{errorMessage(items.error)}</p>}
      {items.data?.length === 0 && (
        <p className="px-4 text-sm text-muted-foreground">
          {q ? "Nothing matches." : "The pantry is empty. Add items here or tell the chat what you bought."}
        </p>
      )}
      <ul className="divide-y">
        {items.data?.map((item) => (
          <ItemRow key={item.id} hid={hid} item={item} />
        ))}
      </ul>
    </div>
  )
}

const ItemRow = ({ hid, item }: { hid: string; item: ItemOut }) => {
  const queryClient = useQueryClient()

  const remove = useDeleteItem({
    mutation: { onSuccess: () => invalidatePantry(queryClient, hid) },
  })

  const fresh = freshness(item)

  return (
    <li className="flex items-center gap-3 px-4 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className={item.quantity <= 0 ? "truncate text-muted-foreground line-through" : "truncate"}>
            {item.name}
          </span>
          {fresh && <Badge variant={fresh.tone === "bad" ? "destructive" : "secondary"}>{fresh.label}</Badge>}
        </div>
        {item.notes !== null && item.notes !== "" && (
          <p className="truncate text-xs text-muted-foreground">{item.notes}</p>
        )}
      </div>
      <span className="text-sm tabular-nums">{formatQuantity(item.quantity, item.unit)}</span>
      <ItemDialog
        hid={hid}
        item={item}
        trigger={
          <Button variant="ghost" size="icon" aria-label={`Edit ${item.name}`}>
            <PencilIcon />
          </Button>
        }
      />
      <Confirm
        trigger={
          <Button variant="ghost" size="icon" aria-label={`Delete ${item.name}`} disabled={remove.isPending}>
            <Trash2Icon />
          </Button>
        }
        title={`Delete ${item.name}?`}
        description="This removes the item and its history. It cannot be undone."
        action="Delete"
        onConfirm={() => {
          remove.mutate({ householdId: hid, itemId: item.id })
        }}
      />
    </li>
  )
}

const ListSkeleton = () => {
  return (
    <div className="flex flex-col gap-2 px-4">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  )
}

export const Route = createFileRoute("/_authed/h/$hid/inventory/")({
  component: Pantry,
})
