import type { QueryClient } from "@tanstack/react-query"
import { getGetRecipeQueryKey, getListRecipesQueryKey } from "@/api/gen/endpoints/recipes/recipes"

export function invalidateRecipes(queryClient: QueryClient, hid: string, rid?: string): Promise<void> {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: getListRecipesQueryKey(hid) }),
    rid ? queryClient.invalidateQueries({ queryKey: getGetRecipeQueryKey(hid, rid) }) : undefined,
  ]).then(() => undefined)
}
