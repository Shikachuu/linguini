import { PlusIcon, XIcon } from "lucide-react";
import { type FormEvent, useState } from "react";
import type { Ingredient, RecipeData, RecipeOut } from "@/api/gen/model";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { UNITS } from "@/lib/pantry";

interface Line {
  key: number;
  name: string;
  quantity: string;
  unit: string;
  optional: boolean;
}

interface RecipeFormProps {
  recipe?: RecipeOut;
  pending: boolean;
  error?: string;
  onSubmit: (data: RecipeData) => void;
}

let nextKey = 0;

function toLine(ingredient?: Ingredient): Line {
  return {
    key: nextKey++,
    name: ingredient?.name ?? "",
    quantity: ingredient ? String(ingredient.quantity) : "",
    unit: ingredient?.unit ?? "g",
    optional: ingredient?.optional ?? false,
  };
}

export function RecipeForm({ recipe, pending, error, onSubmit }: RecipeFormProps) {
  const [title, setTitle] = useState(recipe?.title ?? "");
  const [servings, setServings] = useState(String(recipe?.servings ?? 2));
  const [lines, setLines] = useState<Line[]>(() =>
    recipe?.ingredients.length ? recipe.ingredients.map(toLine) : [toLine()],
  );
  const [steps, setSteps] = useState(recipe?.steps.join("\n") ?? "");
  const [allergens, setAllergens] = useState(recipe?.allergens.join(", ") ?? "");

  function update(key: number, patch: Partial<Line>) {
    setLines((current) => current.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
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
    });
  }

  return (
    <form className="grid gap-4 px-4" onSubmit={submit}>
      <div className="grid gap-1.5">
        <Label htmlFor="recipe-title">Title</Label>
        <Input
          id="recipe-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
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
          onChange={(e) => setServings(e.target.value)}
          required
        />
      </div>
      <fieldset className="grid gap-2">
        <legend className="mb-1.5 text-sm font-medium">Ingredients</legend>
        {lines.map((line, index) => (
          <div key={line.key} className="flex items-center gap-2">
            <Input
              aria-label={`Ingredient ${index + 1} name`}
              placeholder="Name"
              value={line.name}
              onChange={(e) => update(line.key, { name: e.target.value })}
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
              onChange={(e) => update(line.key, { quantity: e.target.value })}
              required={Boolean(line.name.trim())}
              className="w-20"
            />
            <Input
              aria-label={`Ingredient ${index + 1} unit`}
              list="recipe-units"
              value={line.unit}
              onChange={(e) => update(line.key, { unit: e.target.value })}
              className="w-20"
            />
            <label className="text-muted-foreground flex items-center gap-1 text-xs">
              <input
                type="checkbox"
                checked={line.optional}
                onChange={(e) => update(line.key, { optional: e.target.checked })}
              />
              opt.
            </label>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Remove ingredient ${index + 1}`}
              disabled={lines.length === 1}
              onClick={() => setLines((current) => current.filter((l) => l.key !== line.key))}
            >
              <XIcon />
            </Button>
          </div>
        ))}
        <datalist id="recipe-units">
          {UNITS.map((u) => (
            <option key={u} value={u} />
          ))}
        </datalist>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="justify-self-start"
          onClick={() => setLines((current) => [...current, toLine()])}
        >
          <PlusIcon /> Ingredient
        </Button>
      </fieldset>
      <div className="grid gap-1.5">
        <Label htmlFor="recipe-steps">Steps, one per line</Label>
        <Textarea
          id="recipe-steps"
          value={steps}
          onChange={(e) => setSteps(e.target.value)}
          rows={6}
        />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="recipe-allergens">Allergens, comma separated</Label>
        <Input
          id="recipe-allergens"
          value={allergens}
          onChange={(e) => setAllergens(e.target.value)}
        />
      </div>
      {error && <p className="text-destructive text-sm">{error}</p>}
      <Button type="submit" disabled={pending} className="justify-self-start">
        Save
      </Button>
    </form>
  );
}
