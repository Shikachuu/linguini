import { useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { CopyIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { useMe } from "@/api/gen/endpoints/auth/auth"
import {
  getListMembersQueryKey,
  useCreateInvite,
  useDeleteHousehold,
  useGetHousehold,
  useListMembers,
  useRemoveMember,
  useRenameHousehold,
} from "@/api/gen/endpoints/households/households"
import { PageHeader } from "@/components/app-shell"
import { Confirm } from "@/components/confirm"
import { KifliCard } from "@/components/settings/kifli-card"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { errorMessage } from "@/lib/errors"
import { formatDate, formatDateTime } from "@/lib/format"
import { refreshMe } from "@/lib/session"

const Settings = () => {
  const { hid } = Route.useParams()

  return (
    <div className="mx-auto grid max-w-2xl gap-4 pb-6">
      <PageHeader title="Settings" />
      <div className="grid gap-4 px-4">
        <HouseholdCard hid={hid} />
        <MembersCard hid={hid} />
        <KifliCard hid={hid} />
      </div>
    </div>
  )
}

const HouseholdCard = ({ hid }: { hid: string }) => {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const household = useGetHousehold(hid)
  const [name, setName] = useState<string | null>(null)

  const rename = useRenameHousehold({
    mutation: {
      onSuccess: async () => {
        setName(null)
        await Promise.all([refreshMe(queryClient), household.refetch()])
        toast.success("Household renamed")
      },
    },
  })

  const remove = useDeleteHousehold({
    mutation: {
      onSuccess: async () => {
        await refreshMe(queryClient)
        await navigate({ to: "/" })
      },
    },
  })

  const value = name ?? household.data?.name ?? ""

  return (
    <Card>
      <CardHeader>
        <CardTitle>Household</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            rename.mutate({ householdId: hid, data: { name: value.trim() } })
          }}
        >
          <Input
            aria-label="Household name"
            value={value}
            onChange={(e) => {
              setName(e.target.value)
            }}
            maxLength={80}
            required
          />
          <Button type="submit" variant="outline" disabled={name === null || rename.isPending}>
            Rename
          </Button>
        </form>
        {rename.isError && <p className="text-sm text-destructive">{errorMessage(rename.error)}</p>}
        <Confirm
          trigger={
            <Button variant="destructive" className="justify-self-start">
              Delete household
            </Button>
          }
          title="Delete this household?"
          description="This deletes the pantry, recipes, chats and Kifli connection for every member."
          action="Delete"
          typeToConfirm={household.data?.name}
          onConfirm={() => {
            remove.mutate({ householdId: hid })
          }}
        />
      </CardContent>
    </Card>
  )
}

const copyInviteLink = async (url: string) => {
  await navigator.clipboard.writeText(url)
  toast.success("Invite link copied")
}

const InviteLink = ({ hid }: { hid: string }) => {
  const invite = useCreateInvite()

  return (
    <>
      {invite.data ? (
        <div className="grid gap-1">
          <div className="flex gap-2">
            <Input
              readOnly
              value={invite.data.url}
              aria-label="Invite link"
              onFocus={(e) => {
                e.target.select()
              }}
            />
            <Button
              variant="outline"
              size="icon"
              aria-label="Copy invite link"
              onClick={() => void copyInviteLink(invite.data.url)}
            >
              <CopyIcon />
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Single use, valid until {formatDateTime(invite.data.expires_at)}.
          </p>
        </div>
      ) : (
        <Button
          variant="outline"
          className="justify-self-start"
          disabled={invite.isPending}
          onClick={() => {
            invite.mutate({ householdId: hid })
          }}
        >
          Create invite link
        </Button>
      )}
      {invite.isError && <p className="text-sm text-destructive">{errorMessage(invite.error)}</p>}
    </>
  )
}

const MembersCard = ({ hid }: { hid: string }) => {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { data: me } = useMe()
  const members = useListMembers(hid)

  const remove = useRemoveMember({
    mutation: {
      onSuccess: async (_, { userId }) => {
        if (userId === me?.id) {
          await refreshMe(queryClient)
          await navigate({ to: "/" })
        } else {
          await queryClient.invalidateQueries({ queryKey: getListMembersQueryKey(hid) })
        }
      },
    },
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Members</CardTitle>
        <CardDescription>Everyone here shares the pantry, recipes and chats.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {members.isError && <p className="text-sm text-destructive">{errorMessage(members.error)}</p>}
        <ul className="divide-y">
          {members.data?.map((m) => (
            <li key={m.user_id} className="flex items-center gap-2 py-2">
              <span className="min-w-0 flex-1 truncate">
                {m.display_name}
                {m.user_id === me?.id && <span className="text-muted-foreground"> (you)</span>}
              </span>
              <span className="text-xs text-muted-foreground">joined {formatDate(m.joined_at)}</span>
              <Confirm
                trigger={
                  <Button variant="ghost" size="sm">
                    {m.user_id === me?.id ? "Leave" : "Remove"}
                  </Button>
                }
                title={m.user_id === me?.id ? "Leave this household?" : `Remove ${m.display_name}?`}
                description={
                  members.data.length === 1
                    ? "You are the last member, so the household and all of its data will be deleted."
                    : "They can rejoin only with a new invite link."
                }
                action={m.user_id === me?.id ? "Leave" : "Remove"}
                onConfirm={() => {
                  remove.mutate({ householdId: hid, userId: m.user_id })
                }}
              />
            </li>
          ))}
        </ul>
        <InviteLink hid={hid} />
      </CardContent>
    </Card>
  )
}

export const Route = createFileRoute("/_authed/h/$hid/settings")({
  component: Settings,
})
