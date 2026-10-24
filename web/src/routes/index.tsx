import { createFileRoute, redirect } from "@tanstack/react-router"
import { z } from "zod"
import type { MeOut } from "@/api/gen/model"
import { isUnauthorized } from "@/lib/errors"
import { loadMe, pickHousehold } from "@/lib/session"

const nonEmptyText = z.string().min(1)

const searchText = z
  .unknown()
  .optional()
  .transform((value) => nonEmptyText.safeParse(value).data)

const indexSearch = z.object({ login_error: searchText })

export const Route = createFileRoute("/")({
  validateSearch: indexSearch,
  beforeLoad: async ({ context, search }) => {
    if (search.login_error !== undefined) {
      redirect({ to: "/login", search: { login_error: search.login_error }, throw: true })
    }

    let me: MeOut

    try {
      me = await loadMe(context.queryClient)
    } catch (cause) {
      if (isUnauthorized(cause)) redirect({ to: "/login", throw: true })
      throw cause
    }

    const hid = pickHousehold(me.households)

    if (hid !== undefined) redirect({ to: "/h/$hid/chat", params: { hid }, throw: true })
    redirect({ to: "/welcome", throw: true })
  },
})
