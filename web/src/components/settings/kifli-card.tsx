import { useQueryClient } from "@tanstack/react-query"
import { type FormEvent, useState } from "react"
import { ApiError } from "@/api/fetcher"
import {
  getConnectionStatusQueryKey,
  useConnect,
  useConnectionStatus,
  useDisconnect,
  useFinish,
} from "@/api/gen/endpoints/kifli/kifli"
import type { ConnectOut } from "@/api/gen/model"
import { Confirm } from "@/components/confirm"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { errorMessage } from "@/lib/errors"
import { formatDate } from "@/lib/format"

export const callbackErrorMessage = (error: unknown): string => {
  if (error instanceof ApiError) {
    if (error.status === 400) return "That address is not a valid or current sign-in result. Start again with Connect."

    if (error.status === 401) return "Kifli rejected the sign-in. Start again with Connect."

    if (error.status === 502) return "Kifli could not be reached. Try pasting the address again in a moment."
  }

  return errorMessage(error)
}

export const KifliCard = ({ hid }: { hid: string }) => {
  const queryClient = useQueryClient()
  const status = useConnectionStatus(hid)
  const [pending, setPending] = useState<ConnectOut | null>(null)
  const [callbackUrl, setCallbackUrl] = useState("")
  const refresh = () => queryClient.invalidateQueries({ queryKey: getConnectionStatusQueryKey(hid) })

  const connect = useConnect({
    mutation: {
      onSuccess: (data) => {
        setPending(data)
        setCallbackUrl("")
        window.open(data.authorize_url, "_blank", "noopener")
      },
    },
  })

  const finish = useFinish({
    mutation: {
      onSuccess: async () => {
        setPending(null)
        await refresh()
      },
    },
  })

  const disconnect = useDisconnect({ mutation: { onSuccess: refresh } })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    finish.mutate({ householdId: hid, data: { callback_url: callbackUrl.trim() } })
  }

  const s = status.data

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Kifli
          {s?.connected && !s.broken && <Badge variant="secondary">Connected</Badge>}
          {s?.broken && <Badge variant="destructive">Needs reconnecting</Badge>}
        </CardTitle>
        <CardDescription>Connect your Kifli account so the chat can import orders and edit your cart.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {status.isPending && <Skeleton className="h-9 w-40" />}
        {status.isError && <p className="text-sm text-destructive">{errorMessage(status.error)}</p>}
        {s?.connected && s.connected_at && (
          <p className="text-sm text-muted-foreground">
            Connected {formatDate(s.connected_at)}
            {s.expires_at && `, access renews by ${formatDate(s.expires_at)}`}.
          </p>
        )}
        {pending ? (
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
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setPending(null)
                }}
              >
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          s && (
            <div className="flex gap-2">
              {(!s.connected || s.broken) && (
                <Button
                  disabled={connect.isPending}
                  onClick={() => {
                    connect.mutate({ householdId: hid })
                  }}
                >
                  {s.broken ? "Reconnect" : "Connect"}
                </Button>
              )}
              {s.connected && (
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
        )}
        {connect.isError && <p className="text-sm text-destructive">{errorMessage(connect.error)}</p>}
      </CardContent>
    </Card>
  )
}
