import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"
import { isUnauthorized } from "@/lib/errors"
import { loadMe } from "@/lib/session"

export const Route = createFileRoute("/_authed")({
  beforeLoad: async ({ context, location }) => {
    const me = await loadMe(context.queryClient).catch((error: unknown) => {
      if (isUnauthorized(error)) throw redirect({ to: "/login", search: { return_to: location.href } })
      throw error
    })

    return { me }
  },
  component: Outlet,
})
