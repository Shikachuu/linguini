import { createFileRoute } from "@tanstack/react-router"
import { z } from "zod"
import { useConfig } from "@/api/gen/endpoints/meta/meta"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { loginHref, type Provider } from "@/lib/session"

const nonEmptyText = z.string().min(1)

const searchText = z
  .unknown()
  .optional()
  .transform((value) => nonEmptyText.safeParse(value).data)

const loginSearch = z.object({ return_to: searchText, invite: searchText, login_error: searchText })

const PROVIDERS: { id: Provider; label: string }[] = [
  { id: "google", label: "Continue with Google" },
  { id: "apple", label: "Continue with Apple" },
]

const LOGIN_ERRORS = new Map([
  ["invite_required", "You need an invite link from a household member to create an account."],
  ["access_denied", "Sign-in was cancelled."],
])

const loginErrorMessage = (reason: string): string => {
  return LOGIN_ERRORS.get(reason) ?? `Sign-in failed: ${reason}`
}

export const Login = () => {
  const { return_to, invite, login_error } = Route.useSearch()
  const { data: config, isPending, isError } = useConfig()
  const enabled = PROVIDERS.filter((p) => config?.providers[p.id] === true)

  return (
    <main className="flex min-h-dvh items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-2xl">Linguini</CardTitle>
          <CardDescription>
            {invite === undefined ? "Sign in to your household." : "Sign in to join the household you were invited to."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {login_error !== undefined && (
            <p role="alert" className="text-sm text-destructive">
              {loginErrorMessage(login_error)}
            </p>
          )}
          {isPending && <Skeleton className="h-9 w-full" />}
          {isError && <p className="text-sm text-destructive">Could not reach the server.</p>}
          {config && enabled.length === 0 && (
            <p className="text-sm text-muted-foreground">No sign-in provider is configured on this server.</p>
          )}
          {enabled.map((p) => (
            <Button key={p.id} asChild variant="outline" size="lg">
              <a href={loginHref(p.id, { return_to, invite })}>{p.label}</a>
            </Button>
          ))}
        </CardContent>
      </Card>
    </main>
  )
}

export const Route = createFileRoute("/login")({
  validateSearch: loginSearch,
  component: Login,
})
