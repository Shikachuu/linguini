import type { QueryClient } from "@tanstack/react-query"
import { getListEventsQueryKey, getListItemsQueryKey } from "@/api/gen/endpoints/inventory/inventory"
import type { Dimension, ItemOut } from "@/api/gen/model"
import { daysSince } from "@/lib/format"

export const UNITS = ["g", "dkg", "kg", "ml", "dl", "l", "tsp", "tbsp", "cup", "pcs"] as const

export const BASE_UNIT: Record<Dimension, string> = { mass: "g", volume: "ml", count: "pcs" }

const EXPIRY_WINDOW_DAYS = 3

const OLD_PURCHASE_DAYS = 7

export const invalidatePantry = (queryClient: QueryClient, hid: string): Promise<void> => {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: getListItemsQueryKey(hid) }),
    queryClient.invalidateQueries({ queryKey: getListEventsQueryKey(hid) }),
  ]).then(() => {})
}

export type Freshness = { tone: "bad" | "warn"; label: string } | null

export const freshness = (item: ItemOut, now: Date = new Date()): Freshness => {
  if (item.quantity <= 0) return null

  if (item.expires_at) {
    const daysLeft = -daysSince(item.expires_at, now)

    if (daysLeft < 0) return { tone: "bad", label: `expired ${-daysLeft}d ago` }

    if (daysLeft <= EXPIRY_WINDOW_DAYS) return { tone: "warn", label: `expires in ${daysLeft}d` }

    return null
  }

  if (item.last_purchased_at) {
    const age = daysSince(item.last_purchased_at, now)

    if (age >= OLD_PURCHASE_DAYS) return { tone: "warn", label: `bought ${age}d ago` }
  }

  return null
}

export const dateInputValue = (value: string | null): string => {
  return value ? value.slice(0, 10) : ""
}

export const dateFromInput = (value: string): string | null => {
  return value ? new Date(`${value}T00:00:00Z`).toISOString() : null
}
