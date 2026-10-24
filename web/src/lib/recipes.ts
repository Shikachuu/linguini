import type { QueryClient } from "@tanstack/react-query"
import { getGetRecipeQueryKey, getListRecipesQueryKey } from "@/api/gen/endpoints/recipes/recipes"

export const invalidateRecipes = async (queryClient: QueryClient, hid: string, rid?: string): Promise<void> => {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: getListRecipesQueryKey(hid) }),
    rid === undefined ? undefined : queryClient.invalidateQueries({ queryKey: getGetRecipeQueryKey(hid, rid) }),
  ])
}
