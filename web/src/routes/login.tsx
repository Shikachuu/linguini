import { createFileRoute } from "@tanstack/react-router";
import { useConfig } from "@/api/gen/endpoints/meta/meta";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { loginHref, type Provider } from "@/lib/session";

interface LoginSearch {
  return_to?: string;
  invite?: string;
  login_error?: string;
}

const PROVIDERS: { id: Provider; label: string }[] = [
  { id: "google", label: "Continue with Google" },
  { id: "apple", label: "Continue with Apple" },
];

const LOGIN_ERRORS: Record<string, string> = {
  invite_required: "You need an invite link from a household member to create an account.",
  access_denied: "Sign-in was cancelled.",
};

function loginErrorMessage(reason: string): string {
  return LOGIN_ERRORS[reason] ?? `Sign-in failed: ${reason}`;
}

export const Route = createFileRoute("/login")({
  validateSearch: (search: Record<string, unknown>): LoginSearch => {
    const result: LoginSearch = {};
    for (const key of ["return_to", "invite", "login_error"] as const) {
      const value = search[key];
      if (typeof value === "string" && value) result[key] = value;
    }
    return result;
  },
  component: Login,
});

export function Login() {
  const { return_to, invite, login_error } = Route.useSearch();
  const { data: config, isPending, isError } = useConfig();
  const enabled = PROVIDERS.filter((p) => config?.providers[p.id]);

  return (
    <main className="flex min-h-dvh items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-2xl">Linguini</CardTitle>
          <CardDescription>
            {invite
              ? "Sign in to join the household you were invited to."
              : "Sign in to your household."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {login_error && (
            <p role="alert" className="text-destructive text-sm">
              {loginErrorMessage(login_error)}
            </p>
          )}
          {isPending && <Skeleton className="h-9 w-full" />}
          {isError && <p className="text-destructive text-sm">Could not reach the server.</p>}
          {config && enabled.length === 0 && (
            <p className="text-muted-foreground text-sm">
              No sign-in provider is configured on this server.
            </p>
          )}
          {enabled.map((p) => (
            <Button key={p.id} asChild variant="outline" size="lg">
              <a href={loginHref(p.id, { return_to, invite })}>{p.label}</a>
            </Button>
          ))}
        </CardContent>
      </Card>
    </main>
  );
}
