import { createFileRoute, Link, redirect, type ErrorComponentProps } from "@tanstack/react-router"
import { acceptInvite } from "@/api/gen/endpoints/households/households"
import { Button } from "@/components/ui/button"
import { errorMessage, isUnauthorized } from "@/lib/errors"
import { loadMe, refreshMe } from "@/lib/session"

const InviteError = ({ error }: ErrorComponentProps) => {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 p-4 text-center">
      <p>This invite could not be used: {errorMessage(error)}</p>
      <Button asChild variant="outline">
        <Link to="/">Go home</Link>
      </Button>
    </main>
  )
}

export const Route = createFileRoute("/invite/$code")({
  beforeLoad: async ({ context, params }) => {
    try {
      await loadMe(context.queryClient)
    } catch (cause) {
      if (isUnauthorized(cause)) redirect({ to: "/login", search: { invite: params.code }, throw: true })
      throw cause
    }

    const household = await acceptInvite(params.code)

    await refreshMe(context.queryClient)
    redirect({ to: "/h/$hid/chat", params: { hid: household.id }, throw: true })
  },
  errorComponent: InviteError,
})
