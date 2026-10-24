import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"
import type { MeOut } from "@/api/gen/model"
import { isUnauthorized } from "@/lib/errors"
import { loadMe } from "@/lib/session"

export const Route = createFileRoute("/_authed")({
  beforeLoad: async ({ context, location }) => {
    let me: MeOut

    try {
      me = await loadMe(context.queryClient)
    } catch (cause) {
      if (isUnauthorized(cause)) redirect({ to: "/login", search: { return_to: location.href }, throw: true })
      throw cause
    }

    return { me }
  },
  component: Outlet,
})
