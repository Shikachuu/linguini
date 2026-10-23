import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowLeftIcon } from "lucide-react";
import { useListEvents, useListItems } from "@/api/gen/endpoints/inventory/inventory";
import type { EventOut } from "@/api/gen/model";
import { PageHeader } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { UndoButton } from "@/components/undo-button";
import { errorMessage } from "@/lib/errors";
import { formatDateTime, formatQuantity } from "@/lib/format";
import { BASE_UNIT } from "@/lib/pantry";

export const Route = createFileRoute("/_authed/h/$hid/inventory/events")({
  component: History,
});

const CAUSE_LABEL: Record<EventOut["cause"], string> = {
  manual: "Manual",
  chat: "Chat",
  cook: "Cooked",
  kifli_order: "Kifli order",
  undo: "Undo",
};

function History() {
  const { hid } = Route.useParams();
  const events = useListEvents(hid, { limit: 100 });
  const items = useListItems(hid);
  const names = new Map(items.data?.map((i) => [i.id, i.name]));

  return (
    <div className="mx-auto max-w-2xl pb-6">
      <PageHeader
        title={
          <span className="flex items-center gap-1">
            <Button asChild variant="ghost" size="icon" aria-label="Back to pantry">
              <Link to="/h/$hid/inventory" params={{ hid }}>
                <ArrowLeftIcon />
              </Link>
            </Button>
            History
          </span>
        }
      />
      {events.isPending && <Skeleton className="mx-4 h-10" />}
      {events.isError && (
        <p className="text-destructive px-4 text-sm">{errorMessage(events.error)}</p>
      )}
      {events.data?.length === 0 && (
        <p className="text-muted-foreground px-4 text-sm">No changes yet.</p>
      )}
      <ul className="divide-y">
        {events.data?.map((event) => (
          <EventRow
            key={event.id}
            hid={hid}
            event={event}
            name={names.get(event.item_id) ?? "Unknown item"}
          />
        ))}
      </ul>
    </div>
  );
}

function EventRow({ hid, event, name }: { hid: string; event: EventOut; name: string }) {
  const unit = BASE_UNIT[event.dimension];
  const undone = event.undone_by_event_id !== null;
  return (
    <li className="flex items-center gap-3 px-4 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className={undone ? "text-muted-foreground truncate line-through" : "truncate"}>
            {name}
          </span>
          <Badge variant="outline">{CAUSE_LABEL[event.cause]}</Badge>
        </div>
        <p className="text-muted-foreground text-xs">
          {formatQuantity(event.quantity_before, unit)} {"->"}{" "}
          {formatQuantity(event.quantity_after, unit)} · {formatDateTime(event.created_at)}
        </p>
      </div>
      {!undone && event.cause !== "undo" && <UndoButton hid={hid} eventId={event.id} />}
    </li>
  );
}
