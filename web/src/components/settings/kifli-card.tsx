import { useQueryClient } from "@tanstack/react-query"
import { type SubmitEvent, useState } from "react"
import { ApiError } from "@/api/fetcher"
import {
  getConnectionStatusQueryKey,
  useConnect,
  useConnectionStatus,
  useDisconnect,
  useFinish,
} from "@/api/gen/endpoints/kifli/kifli"
import type { ConnectionOut, ConnectOut } from "@/api/gen/model"
import { Confirm } from "@/components/confirm"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { errorMessage } from "@/lib/errors"
import { formatDate } from "@/lib/format"

const callbackErrorMessage = (cause: unknown): string => {
  if (cause instanceof ApiError) {
    if (cause.status === 400) return "That address is not a valid or current sign-in result. Start again with Connect."

    if (cause.status === 401) return "Kifli rejected the sign-in. Start again with Connect."

    if (cause.status === 502) return "Kifli could not be reached. Try pasting the address again in a moment."
  }

  return errorMessage(cause)
}

const useRefreshStatus = (hid: string) => {
  const queryClient = useQueryClient()

  return () => queryClient.invalidateQueries({ queryKey: getConnectionStatusQueryKey(hid) })
}

const StatusBadge = ({ connection }: { connection: ConnectionOut }) => {
  if (connection.broken === true) return <Badge variant="destructive">Needs reconnecting</Badge>

  if (connection.connected) return <Badge variant="secondary">Connected</Badge>

  return null
}

const ConnectionSummary = ({ connection }: { connection: ConnectionOut }) => {
  const connectedAt = connection.connected_at ?? null
  const expiresAt = connection.expires_at ?? null

  if (!connection.connected || connectedAt === null) return null

  return (
    <p className="text-sm text-muted-foreground">
      Connected {formatDate(connectedAt)}
      {expiresAt !== null && `, access renews by ${formatDate(expiresAt)}`}.
    </p>
  )
}

const CallbackForm = ({ hid, pending, onDone }: { hid: string; pending: ConnectOut; onDone: () => void }) => {
  const refresh = useRefreshStatus(hid)
  const [callbackUrl, setCallbackUrl] = useState("")

  const finish = useFinish({
    mutation: {
      onSuccess: async () => {
        onDone()
        await refresh()
      },
    },
  })

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault()
    finish.mutate({ householdId: hid, data: { callback_url: callbackUrl.trim() } })
  }

  return (
    <form className="grid gap-2" onSubmit={submit}>
      <p className="text-sm">{pending.instructions}</p>
      <a className="text-sm underline" href={pending.authorize_url} target="_blank" rel="noreferrer noopener">
        Open the Kifli sign-in page again
      </a>
      <Label htmlFor="kifli-callback">Address from the address bar</Label>
      <Input
        id="kifli-callback"
        value={callbackUrl}
        onChange={(e) => {
          setCallbackUrl(e.target.value)
        }}
        placeholder={`${pending.redirect_uri}?code=...`}
        required
      />
      {finish.isError && <p className="text-sm text-destructive">{callbackErrorMessage(finish.error)}</p>}
      <div className="flex gap-2">
        <Button type="submit" disabled={finish.isPending}>
          Finish connecting
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

type ConnectionActionsProps = {
  hid: string
  connection: ConnectionOut
  connecting: boolean
  onConnect: () => void
}

const ConnectionActions = ({ hid, connection, connecting, onConnect }: ConnectionActionsProps) => {
  const refresh = useRefreshStatus(hid)
  const disconnect = useDisconnect({ mutation: { onSuccess: refresh } })
  const broken = connection.broken === true

  return (
    <div className="flex gap-2">
      {(!connection.connected || broken) && (
        <Button disabled={connecting} onClick={onConnect}>
          {broken ? "Reconnect" : "Connect"}
        </Button>
      )}
      {connection.connected && (
        <Confirm
          trigger={<Button variant="outline">Disconnect</Button>}
          title="Disconnect Kifli?"
          description="The chat will no longer see your orders or cart."
          action="Disconnect"
          onConfirm={() => {
            disconnect.mutate({ householdId: hid })
          }}
        />
      )}
    </div>
  )
}

export const KifliCard = ({ hid }: { hid: string }) => {
  const status = useConnectionStatus(hid)
  const [pending, setPending] = useState<ConnectOut | null>(null)

  const connect = useConnect({
    mutation: {
      onSuccess: (data) => {
        setPending(data)
        window.open(data.authorize_url, "_blank", "noopener")
      },
    },
  })

  const connection = status.data

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Kifli
          {connection !== undefined && <StatusBadge connection={connection} />}
        </CardTitle>
        <CardDescription>Connect your Kifli account so the chat can import orders and edit your cart.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {status.isPending && <Skeleton className="h-9 w-40" />}
        {status.isError && <p className="text-sm text-destructive">{errorMessage(status.error)}</p>}
        {connection !== undefined && <ConnectionSummary connection={connection} />}
        {pending === null ? (
          connection !== undefined && (
            <ConnectionActions
              hid={hid}
              connection={connection}
              connecting={connect.isPending}
              onConnect={() => {
                connect.mutate({ householdId: hid })
              }}
            />
          )
        ) : (
          <CallbackForm
            key={pending.authorize_url}
            hid={hid}
            pending={pending}
            onDone={() => {
              setPending(null)
            }}
          />
        )}
        {connect.isError && <p className="text-sm text-destructive">{errorMessage(connect.error)}</p>}
      </CardContent>
    </Card>
  )
}
