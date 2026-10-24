import { useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useState } from "react"
import { useCreateHousehold } from "@/api/gen/endpoints/households/households"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { errorMessage } from "@/lib/errors"
import { refreshMe } from "@/lib/session"

export const Route = createFileRoute("/_authed/welcome")({
  component: Welcome,
})

function Welcome() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [name, setName] = useState("")
  const create = useCreateHousehold({
    mutation: {
      onSuccess: async (household) => {
        await refreshMe(queryClient)
        await navigate({ to: "/h/$hid/chat", params: { hid: household.id } })
      },
    },
  })

  return (
    <main className="flex min-h-dvh items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Create a household</CardTitle>
          <CardDescription>
            A household shares one pantry and its chats. To join an existing one, open an invite link from a member.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
              event.preventDefault()
              create.mutate({ data: { name: name.trim() } })
            }}
          >
            <Label htmlFor="household-name">Name</Label>
            <Input
              id="household-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Home"
              required
              maxLength={80}
            />
            {create.isError && <p className="text-sm text-destructive">{errorMessage(create.error)}</p>}
            <Button type="submit" disabled={!name.trim() || create.isPending}>
              Create
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  )
}
