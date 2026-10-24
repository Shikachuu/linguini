import { useQueryClient } from "@tanstack/react-query"
import { CheckIcon, CookingPotIcon, XIcon } from "lucide-react"
import { useState } from "react"
import { useCookRecipe } from "@/api/gen/endpoints/recipes/recipes"
import type { RecipeOut } from "@/api/gen/model"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { UndoButton } from "@/components/undo-button"
import { errorMessage } from "@/lib/errors"
import { invalidatePantry } from "@/lib/pantry"

export function CookDialog({ hid, recipe }: { hid: string; recipe: RecipeOut }) {
  const queryClient = useQueryClient()
  const [servings, setServings] = useState(String(recipe.servings))
  const cook = useCookRecipe({ mutation: { onSuccess: () => invalidatePantry(queryClient, hid) } })

  return (
    <Dialog
      onOpenChange={(open) => {
        if (open) {
          cook.reset()
          setServings(String(recipe.servings))
        }
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm">
          <CookingPotIcon /> Cook
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Cook {recipe.title}</DialogTitle>
          <DialogDescription>Uses up the ingredients from the pantry.</DialogDescription>
        </DialogHeader>
        {cook.data ? (
          <ul className="grid gap-2" aria-label="Cook results">
            {cook.data.results.map((line) => (
              <li key={line.name} className="flex items-center gap-2 text-sm">
                {line.ok ? (
                  <CheckIcon className="size-4 text-green-600" aria-label="done" />
                ) : (
                  <XIcon className="size-4 text-destructive" aria-label="failed" />
                )}
                <span className="min-w-0 flex-1">{line.message}</span>
                {line.event_id && <UndoButton hid={hid} eventId={line.event_id} />}
              </li>
            ))}
          </ul>
        ) : (
          <form
            className="grid gap-3"
            onSubmit={(event) => {
              event.preventDefault()
              cook.mutate({
                householdId: hid,
                recipeId: recipe.id,
                data: { servings: Number(servings) },
              })
            }}
          >
            <div className="grid w-32 gap-1.5">
              <Label htmlFor="cook-servings">Servings</Label>
              <Input
                id="cook-servings"
                type="number"
                min={1}
                max={100}
                value={servings}
                onChange={(e) => setServings(e.target.value)}
                required
              />
            </div>
            {cook.isError && <p className="text-sm text-destructive">{errorMessage(cook.error)}</p>}
            <DialogFooter>
              <Button type="submit" disabled={cook.isPending}>
                Cook
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
