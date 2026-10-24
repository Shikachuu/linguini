import { hashKey, MutationCache, QueryCache, QueryClient } from "@tanstack/react-query"
import { createRouter, type RouterHistory } from "@tanstack/react-router"
import { getMeQueryKey } from "@/api/gen/endpoints/auth/auth"
import { isUnauthorized } from "@/lib/errors"
import { routeTree } from "./routeTree.gen"

export type RouterContext = {
  queryClient: QueryClient
}

export const createAppRouter = (history?: RouterHistory) => {
  const sessionQueryHash = hashKey(getMeQueryKey())

  const redirectToLoginOnUnauthorized = (error: unknown) => {
    if (!isUnauthorized(error) || router.state.location.pathname === "/login") return
    queryClient.clear()
    void router.navigate({ to: "/login", search: { return_to: router.state.location.href } })
  }

  const queryClient = new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        const routeGuardsHandleIt = query.queryHash === sessionQueryHash

        if (!routeGuardsHandleIt) redirectToLoginOnUnauthorized(error)
      },
    }),
    mutationCache: new MutationCache({ onError: redirectToLoginOnUnauthorized }),
    defaultOptions: {
      queries: { staleTime: 30_000, retry: (count, error) => !isUnauthorized(error) && count < 2 },
    },
  })

  const router = createRouter({
    routeTree,
    history,
    context: { queryClient },
    defaultPreload: "intent",
    defaultPreloadStaleTime: 0,
    scrollRestoration: true,
  })

  return router
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}
