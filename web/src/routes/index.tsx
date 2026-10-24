import { createFileRoute, redirect } from "@tanstack/react-router"
import { isUnauthorized } from "@/lib/errors"
import { loadMe, pickHousehold } from "@/lib/session"

export const Route = createFileRoute("/")({
  validateSearch: (search: Record<string, unknown>): { login_error?: string } =>
    typeof search.login_error === "string" ? { login_error: search.login_error } : {},
  beforeLoad: async ({ context, search }) => {
    if (search.login_error) throw redirect({ to: "/login", search: { login_error: search.login_error } })
    const me = await loadMe(context.queryClient).catch((error: unknown) => {
      if (isUnauthorized(error)) throw redirect({ to: "/login" })
      throw error
    })
    const hid = pickHousehold(me.households)
    if (hid) throw redirect({ to: "/h/$hid/chat", params: { hid } })
    throw redirect({ to: "/welcome" })
  },
})
