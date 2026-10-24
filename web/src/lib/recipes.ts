import type { QueryClient } from "@tanstack/react-query"
import { getGetRecipeQueryKey, getListRecipesQueryKey } from "@/api/gen/endpoints/recipes/recipes"

export const invalidateRecipes = async (queryClient: QueryClient, hid: string, rid?: string): Promise<void> => {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: getListRecipesQueryKey(hid) }),
    rid === undefined ? undefined : queryClient.invalidateQueries({ queryKey: getGetRecipeQueryKey(hid, rid) }),
  ])
}

export const keyedSteps = (steps: string[]): { key: string; step: string }[] => {
  const seen = new Map<string, number>()

  return steps.map((step) => {
    const occurrence = seen.get(step) ?? 0

    seen.set(step, occurrence + 1)

    return { key: `${step}#${occurrence}`, step }
  })
}
