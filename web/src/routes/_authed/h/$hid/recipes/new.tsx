import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useCreateRecipe } from "@/api/gen/endpoints/recipes/recipes";
import { PageHeader } from "@/components/app-shell";
import { RecipeForm } from "@/components/recipes/recipe-form";
import { errorMessage } from "@/lib/errors";
import { invalidateRecipes } from "@/lib/recipes";

export const Route = createFileRoute("/_authed/h/$hid/recipes/new")({
  component: NewRecipe,
});

function NewRecipe() {
  const { hid } = Route.useParams();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const create = useCreateRecipe({
    mutation: {
      onSuccess: async (recipe) => {
        await invalidateRecipes(queryClient, hid);
        await navigate({ to: "/h/$hid/recipes/$rid", params: { hid, rid: recipe.id } });
      },
    },
  });
  return (
    <div className="mx-auto max-w-2xl pb-6">
      <PageHeader title="New recipe" />
      <RecipeForm
        pending={create.isPending}
        error={create.error ? errorMessage(create.error) : undefined}
        onSubmit={(data) => create.mutate({ householdId: hid, data })}
      />
    </div>
  );
}
