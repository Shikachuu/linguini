import { createFileRoute, Link, redirect } from "@tanstack/react-router";
import { acceptInvite } from "@/api/gen/endpoints/households/households";
import { Button } from "@/components/ui/button";
import { errorMessage, isUnauthorized } from "@/lib/errors";
import { loadMe, refreshMe } from "@/lib/session";

export const Route = createFileRoute("/invite/$code")({
  beforeLoad: async ({ context, params }) => {
    await loadMe(context.queryClient).catch((error: unknown) => {
      if (isUnauthorized(error)) throw redirect({ to: "/login", search: { invite: params.code } });
      throw error;
    });
    const household = await acceptInvite(params.code);
    await refreshMe(context.queryClient);
    throw redirect({ to: "/h/$hid/chat", params: { hid: household.id } });
  },
  errorComponent: InviteError,
});

function InviteError({ error }: { error: unknown }) {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 p-4 text-center">
      <p>This invite could not be used: {errorMessage(error)}</p>
      <Button asChild variant="outline">
        <Link to="/">Go home</Link>
      </Button>
    </main>
  );
}
