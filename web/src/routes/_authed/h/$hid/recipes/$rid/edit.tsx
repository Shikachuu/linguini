import { useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useGetRecipe, useReplaceRecipe } from "@/api/gen/endpoints/recipes/recipes"
import { PageHeader } from "@/components/app-shell"
import { RecipeForm } from "@/components/recipes/recipe-form"
import { Skeleton } from "@/components/ui/skeleton"
import { errorMessage } from "@/lib/errors"
import { invalidateRecipes } from "@/lib/recipes"

const EditRecipe = () => {
  const { hid, rid } = Route.useParams()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const recipe = useGetRecipe(hid, rid)

  const replace = useReplaceRecipe({
    mutation: {
      onSuccess: async () => {
        await invalidateRecipes(queryClient, hid, rid)
        await navigate({ to: "/h/$hid/recipes/$rid", params: { hid, rid } })
      },
    },
  })

  return (
    <div className="mx-auto max-w-2xl pb-6">
      <PageHeader title="Edit recipe" />
      {recipe.isPending && <Skeleton className="mx-4 h-40" />}
      {recipe.isError && <p className="px-4 text-sm text-destructive">{errorMessage(recipe.error)}</p>}
      {recipe.data && (
        <RecipeForm
          recipe={recipe.data}
          pending={replace.isPending}
          error={replace.error ? errorMessage(replace.error) : undefined}
          onSubmit={(data) => {
            replace.mutate({ householdId: hid, recipeId: rid, data })
          }}
        />
      )}
    </div>
  )
}

export const Route = createFileRoute("/_authed/h/$hid/recipes/$rid/edit")({
  component: EditRecipe,
})
