import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { useUndoEvent } from "@/api/gen/endpoints/inventory/inventory"
import { Button } from "@/components/ui/button"
import { errorMessage } from "@/lib/errors"
import { invalidatePantry } from "@/lib/pantry"

export const UndoButton = ({ hid, eventId }: { hid: string; eventId: string }) => {
  const queryClient = useQueryClient()

  const undo = useUndoEvent({
    mutation: {
      onSuccess: () => invalidatePantry(queryClient, hid),
      onError: (error) => toast.error(errorMessage(error)),
    },
  })

  if (undo.isSuccess) return <span className="text-xs text-muted-foreground">Undone</span>

  return (
    <Button
      variant="outline"
      size="xs"
      disabled={undo.isPending}
      onClick={() => {
        undo.mutate({ householdId: hid, eventId })
      }}
    >
      Undo
    </Button>
  )
}
