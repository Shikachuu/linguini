import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"
import { AppShell } from "@/components/app-shell"
import { rememberHousehold } from "@/lib/session"

const Household = () => {
  const { hid } = Route.useParams()

  return (
    <AppShell hid={hid}>
      <Outlet />
    </AppShell>
  )
}

export const Route = createFileRoute("/_authed/h/$hid")({
  beforeLoad: ({ context, params }) => {
    if (!context.me.households.some((h) => h.id === params.hid)) throw redirect({ to: "/" })
    rememberHousehold(params.hid)
  },
  component: Household,
})
