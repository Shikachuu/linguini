import { useQueryClient } from "@tanstack/react-query"
import { type FormEvent, type ReactNode, useState } from "react"
import { useAddItem, usePatchItem } from "@/api/gen/endpoints/inventory/inventory"
import type { ItemOut } from "@/api/gen/model"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { errorMessage } from "@/lib/errors"
import { dateFromInput, dateInputValue, invalidatePantry, UNITS } from "@/lib/pantry"

interface ItemDialogProps {
  hid: string
  item?: ItemOut
  trigger: ReactNode
}

export function ItemDialog({ hid, item, trigger }: ItemDialogProps) {
  const [open, setOpen] = useState(false)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{item ? `Edit ${item.name}` : "Add to pantry"}</DialogTitle>
        </DialogHeader>
        {open && <ItemForm hid={hid} item={item} onDone={() => setOpen(false)} />}
      </DialogContent>
    </Dialog>
  )
}

function ItemForm({ hid, item, onDone }: { hid: string; item?: ItemOut; onDone: () => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(item?.name ?? "")
  const [quantity, setQuantity] = useState(item ? String(item.quantity) : "")
  const [unit, setUnit] = useState(item?.unit ?? "pcs")
  const [expires, setExpires] = useState(dateInputValue(item?.expires_at ?? null))
  const [notes, setNotes] = useState(item?.notes ?? "")
  const mutation = { onSuccess: () => invalidatePantry(queryClient, hid).then(onDone) }
  const add = useAddItem({ mutation })
  const patch = usePatchItem({ mutation })
  const pending = add.isPending || patch.isPending
  const error = add.error ?? patch.error

  function submit(event: FormEvent) {
    event.preventDefault()
    const fields = {
      quantity: Number(quantity),
      unit: unit.trim(),
      expires_at: dateFromInput(expires),
      notes: notes.trim() || null,
    }
    if (item) patch.mutate({ householdId: hid, itemId: item.id, data: fields })
    else add.mutate({ householdId: hid, data: { name: name.trim(), ...fields } })
  }

  return (
    <form className="grid gap-3" onSubmit={submit}>
      {!item && (
        <div className="grid gap-1.5">
          <Label htmlFor="item-name">Name</Label>
          <Input id="item-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={80} />
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        <div className="grid gap-1.5">
          <Label htmlFor="item-quantity">{item ? "Quantity" : "Amount to add"}</Label>
          <Input
            id="item-quantity"
            type="number"
            inputMode="decimal"
            min={0}
            step="any"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            required
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="item-unit">Unit</Label>
          <Input id="item-unit" list="units" value={unit} onChange={(e) => setUnit(e.target.value)} required />
          <datalist id="units">
            {UNITS.map((u) => (
              <option key={u} value={u} />
            ))}
          </datalist>
        </div>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="item-expires">Expires</Label>
        <Input id="item-expires" type="date" value={expires} onChange={(e) => setExpires(e.target.value)} />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="item-notes">Notes</Label>
        <Textarea id="item-notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(error)}
        </p>
      )}
      <DialogFooter>
        <Button type="submit" disabled={pending}>
          {item ? "Save" : "Add"}
        </Button>
      </DialogFooter>
    </form>
  )
}
