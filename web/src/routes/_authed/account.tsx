import { useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router"
import { ArrowLeftIcon } from "lucide-react"
import { useDeleteMe, useLogout, useMe } from "@/api/gen/endpoints/auth/auth"
import { useConfig } from "@/api/gen/endpoints/meta/meta"
import { Confirm } from "@/components/confirm"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { errorMessage } from "@/lib/errors"
import { loginHref, type Provider } from "@/lib/session"

export const Route = createFileRoute("/_authed/account")({
  component: Account,
})

const PROVIDER_LABEL: Record<Provider, string> = { google: "Google", apple: "Apple" }
const DELETE_CONFIRMATION = "delete my account"

function Account() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { data: me } = useMe()
  const { data: config } = useConfig()
  const signOut = async () => {
    queryClient.clear()
    await navigate({ to: "/login" })
  }
  const logout = useLogout({ mutation: { onSuccess: signOut } })
  const deleteMe = useDeleteMe({ mutation: { onSuccess: signOut } })

  const linked = new Set(me?.identities.map((i) => i.provider))
  const linkable = (Object.keys(PROVIDER_LABEL) as Provider[]).filter((p) => config?.providers[p] && !linked.has(p))

  return (
    <main className="mx-auto grid max-w-2xl gap-4 p-4">
      <div className="flex items-center gap-1">
        <Button asChild variant="ghost" size="icon" aria-label="Back">
          <Link to="/">
            <ArrowLeftIcon />
          </Link>
        </Button>
        <h1 className="text-xl font-semibold">Account</h1>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>{me?.display_name}</CardTitle>
          <CardDescription>Sign-in methods</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <ul className="grid gap-1 text-sm">
            {me?.identities.map((i) => (
              <li key={i.provider}>
                {PROVIDER_LABEL[i.provider]}
                {i.email && <span className="text-muted-foreground"> · {i.email}</span>}
              </li>
            ))}
          </ul>
          {linkable.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {linkable.map((p) => (
                <Button key={p} asChild variant="outline" size="sm">
                  <a href={loginHref(p, { return_to: "/account" })}>Link {PROVIDER_LABEL[p]}</a>
                </Button>
              ))}
            </div>
          )}
          <Button
            variant="outline"
            className="justify-self-start"
            disabled={logout.isPending}
            onClick={() => logout.mutate()}
          >
            Sign out
          </Button>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Delete account</CardTitle>
          <CardDescription>
            Removes your sign-in methods and memberships. Households you are the last member of are deleted with all of
            their data.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2">
          <Confirm
            trigger={
              <Button variant="destructive" className="justify-self-start">
                Delete account
              </Button>
            }
            title="Delete your account?"
            description={`This cannot be undone. Type "${DELETE_CONFIRMATION}" to confirm.`}
            action="Delete account"
            typeToConfirm={DELETE_CONFIRMATION}
            onConfirm={() => deleteMe.mutate()}
          />
          {deleteMe.isError && <p className="text-sm text-destructive">{errorMessage(deleteMe.error)}</p>}
        </CardContent>
      </Card>
    </main>
  )
}
