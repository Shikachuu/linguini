import { hashKey, MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { createRouter, type RouterHistory } from "@tanstack/react-router";
import { getMeQueryKey } from "@/api/gen/endpoints/auth/auth";
import { isUnauthorized } from "@/lib/errors";
import { routeTree } from "./routeTree.gen";

export interface RouterContext {
  queryClient: QueryClient;
}

export function createAppRouter(history?: RouterHistory) {
  const meKey = hashKey(getMeQueryKey());
  const onError = (error: unknown) => {
    if (!isUnauthorized(error) || router.state.location.pathname === "/login") return;
    queryClient.clear();
    void router.navigate({ to: "/login", search: { return_to: router.state.location.href } });
  };
  const queryClient = new QueryClient({
    // Route guards redirect on a 401 from the session query themselves, keeping the target URL and invite code.
    queryCache: new QueryCache({
      onError: (error, query) => query.queryHash !== meKey && onError(error),
    }),
    mutationCache: new MutationCache({ onError }),
    defaultOptions: {
      queries: { staleTime: 30_000, retry: (count, error) => !isUnauthorized(error) && count < 2 },
    },
  });
  const router = createRouter({
    routeTree,
    history,
    context: { queryClient },
    defaultPreload: "intent",
    defaultPreloadStaleTime: 0,
    scrollRestoration: true,
  });
  return router;
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
