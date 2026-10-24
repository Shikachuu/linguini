import { PlusIcon, XIcon } from "lucide-react"
import { type Dispatch, type SetStateAction, type SubmitEvent, useState } from "react"
import type { Ingredient, RecipeData, RecipeOut } from "@/api/gen/model"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { UNITS } from "@/lib/pantry"

type Line = {
  key: number
  name: string
  quantity: string
  unit: string
  optional: boolean
}

type RecipeFormProps = {
  recipe?: RecipeOut
  pending: boolean
  error?: string
  onSubmit: (data: RecipeData) => void
}

let nextKey = 0

const toLine = (ingredient?: Ingredient): Line => {
  return {
    key: nextKey++,
    name: ingredient?.name ?? "",
    quantity: ingredient ? String(ingredient.quantity) : "",
    unit: ingredient?.unit ?? "g",
    optional: ingredient?.optional ?? false,
  }
}

export const RecipeForm = ({ recipe, pending, error, onSubmit }: RecipeFormProps) => {
  const [title, setTitle] = useState(recipe?.title ?? "")
  const [servings, setServings] = useState(String(recipe?.servings ?? 2))

  const [lines, setLines] = useState<Line[]>(() =>
    recipe !== undefined && recipe.ingredients.length > 0 ? recipe.ingredients.map(toLine) : [toLine()],
  )

  const [steps, setSteps] = useState(recipe?.steps.join("\n") ?? "")
  const [allergens, setAllergens] = useState(recipe?.allergens.join(", ") ?? "")

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault()
    onSubmit({
      title: title.trim(),
      servings: Number(servings),
      ingredients: lines
        .filter((l) => l.name.trim())
        .map((l) => ({
          name: l.name.trim(),
          quantity: Number(l.quantity),
          unit: l.unit.trim(),
          optional: l.optional,
        })),
      steps: steps
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
      allergens: allergens
        .split(",")
        .map((a) => a.trim())
        .filter(Boolean),
    })
  }

  return (
    <form className="grid gap-4 px-4" onSubmit={submit}>
      <div className="grid gap-1.5">
        <Label htmlFor="recipe-title">Title</Label>
        <Input
          id="recipe-title"
          value={title}
          onChange={(e) => {
            setTitle(e.target.value)
          }}
          required
          maxLength={120}
        />
      </div>
      <div className="grid w-32 gap-1.5">
        <Label htmlFor="recipe-servings">Servings</Label>
        <Input
          id="recipe-servings"
          type="number"
          min={1}
          max={100}
          value={servings}
          onChange={(e) => {
            setServings(e.target.value)
          }}
          required
        />
      </div>
      <IngredientsFieldset lines={lines} setLines={setLines} />
      <div className="grid gap-1.5">
        <Label htmlFor="recipe-steps">Steps, one per line</Label>
        <Textarea
          id="recipe-steps"
          value={steps}
          onChange={(e) => {
            setSteps(e.target.value)
          }}
          rows={6}
        />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="recipe-allergens">Allergens, comma separated</Label>
        <Input
          id="recipe-allergens"
          value={allergens}
          onChange={(e) => {
            setAllergens(e.target.value)
          }}
        />
      </div>
      {error !== undefined && <p className="text-sm text-destructive">{error}</p>}
      <Button type="submit" disabled={pending} className="justify-self-start">
        Save
      </Button>
    </form>
  )
}

type IngredientRowProps = {
  line: Line
  index: number
  removable: boolean
  onChange: (patch: Partial<Line>) => void
  onRemove: () => void
}

const IngredientRow = ({ line, index, removable, onChange, onRemove }: IngredientRowProps) => {
  return (
    <div className="flex items-center gap-2">
      <Input
        aria-label={`Ingredient ${index + 1} name`}
        placeholder="Name"
        value={line.name}
        onChange={(e) => {
          onChange({ name: e.target.value })
        }}
        maxLength={80}
        className="min-w-0 flex-1"
      />
      <Input
        aria-label={`Ingredient ${index + 1} quantity`}
        type="number"
        inputMode="decimal"
        min={0}
        step="any"
        placeholder="Qty"
        value={line.quantity}
        onChange={(e) => {
          onChange({ quantity: e.target.value })
        }}
        required={Boolean(line.name.trim())}
        className="w-20"
      />
      <Input
        aria-label={`Ingredient ${index + 1} unit`}
        list="recipe-units"
        value={line.unit}
        onChange={(e) => {
          onChange({ unit: e.target.value })
        }}
        className="w-20"
      />
      <label className="flex items-center gap-1 text-xs text-muted-foreground">
        <input
          type="checkbox"
          checked={line.optional}
          onChange={(e) => {
            onChange({ optional: e.target.checked })
          }}
        />
        opt.
      </label>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={`Remove ingredient ${index + 1}`}
        disabled={!removable}
        onClick={onRemove}
      >
        <XIcon />
      </Button>
    </div>
  )
}

const IngredientsFieldset = ({ lines, setLines }: { lines: Line[]; setLines: Dispatch<SetStateAction<Line[]>> }) => {
  return (
    <fieldset className="grid gap-2">
      <legend className="mb-1.5 text-sm font-medium">Ingredients</legend>
      {lines.map((line, index) => (
        <IngredientRow
          key={line.key}
          line={line}
          index={index}
          removable={lines.length > 1}
          onChange={(patch) => {
            setLines((current) => current.map((l) => (l.key === line.key ? { ...l, ...patch } : l)))
          }}
          onRemove={() => {
            setLines((current) => current.filter((l) => l.key !== line.key))
          }}
        />
      ))}
      <datalist id="recipe-units">
        {UNITS.map((u) => (
          <option key={u} value={u}>
            {u}
          </option>
        ))}
      </datalist>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="justify-self-start"
        onClick={() => {
          setLines((current) => [...current, toLine()])
        }}
      >
        <PlusIcon /> Ingredient
      </Button>
    </fieldset>
  )
}
