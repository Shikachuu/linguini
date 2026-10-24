import { useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router"
import { PencilIcon, Trash2Icon } from "lucide-react"
import { useDeleteRecipe, useGetRecipe } from "@/api/gen/endpoints/recipes/recipes"
import { PageHeader } from "@/components/app-shell"
import { Confirm } from "@/components/confirm"
import { CookDialog } from "@/components/recipes/cook-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { errorMessage } from "@/lib/errors"
import { formatQuantity } from "@/lib/format"
import { invalidateRecipes, keyedSteps } from "@/lib/recipes"

const RecipeView = () => {
  const { hid, rid } = Route.useParams()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const recipe = useGetRecipe(hid, rid)

  const remove = useDeleteRecipe({
    mutation: {
      onSuccess: async () => {
        await invalidateRecipes(queryClient, hid)
        await navigate({ to: "/h/$hid/recipes", params: { hid } })
      },
    },
  })

  if (recipe.isPending) return <Skeleton className="m-4 h-40" />

  if (recipe.isError) return <p className="p-4 text-sm text-destructive">{errorMessage(recipe.error)}</p>
  const r = recipe.data

  return (
    <article className="mx-auto max-w-2xl pb-6">
      <PageHeader
        title={r.title}
        actions={
          <>
            <CookDialog hid={hid} recipe={r} />
            <Button asChild variant="ghost" size="icon" aria-label="Edit recipe">
              <Link to="/h/$hid/recipes/$rid/edit" params={{ hid, rid }}>
                <PencilIcon />
              </Link>
            </Button>
            <Confirm
              trigger={
                <Button variant="ghost" size="icon" aria-label="Delete recipe">
                  <Trash2Icon />
                </Button>
              }
              title={`Delete ${r.title}?`}
              description="The recipe is removed for everyone in the household."
              action="Delete"
              onConfirm={() => {
                remove.mutate({ householdId: hid, recipeId: rid })
              }}
            />
          </>
        }
      />
      <div className="grid gap-5 px-4">
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <span>{r.servings} servings</span>
          {r.allergens.map((a) => (
            <Badge key={a} variant="outline">
              {a}
            </Badge>
          ))}
        </div>
        <section>
          <h2 className="mb-2 font-medium">Ingredients</h2>
          <ul className="grid gap-1 text-sm">
            {r.ingredients.map((i) => (
              <li key={i.name} className="flex justify-between gap-4">
                <span>
                  {i.name}
                  {i.optional === true && <span className="text-muted-foreground"> (optional)</span>}
                </span>
                <span className="tabular-nums">{formatQuantity(i.quantity, i.unit)}</span>
              </li>
            ))}
          </ul>
        </section>
        {r.steps.length > 0 && (
          <section>
            <h2 className="mb-2 font-medium">Steps</h2>
            <ol className="grid list-decimal gap-2 pl-5 text-sm">
              {keyedSteps(r.steps).map(({ key, step }) => (
                <li key={key}>{step}</li>
              ))}
            </ol>
          </section>
        )}
      </div>
    </article>
  )
}

export const Route = createFileRoute("/_authed/h/$hid/recipes/$rid/")({
  component: RecipeView,
})
