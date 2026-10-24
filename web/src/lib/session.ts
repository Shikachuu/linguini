import type { QueryClient } from "@tanstack/react-query"
import { getMeQueryKey, getMeQueryOptions } from "@/api/gen/endpoints/auth/auth"
import type { HouseholdRef, MeOut } from "@/api/gen/model"

const LAST_HOUSEHOLD = "linguini:last-household"

export type Provider = "google" | "apple"

export function loadMe(queryClient: QueryClient): Promise<MeOut> {
  return queryClient.ensureQueryData(getMeQueryOptions())
}

export function rememberHousehold(id: string): void {
  localStorage.setItem(LAST_HOUSEHOLD, id)
}

export function pickHousehold(households: HouseholdRef[]): string | undefined {
  const last = localStorage.getItem(LAST_HOUSEHOLD)
  return households.find((h) => h.id === last)?.id ?? households[0]?.id
}

export function loginHref(provider: Provider, params: { return_to?: string; invite?: string } = {}): string {
  const query = new URLSearchParams()
  if (params.return_to) query.set("return_to", params.return_to)
  if (params.invite) query.set("invite", params.invite)
  const suffix = query.size ? `?${query}` : ""
  return `/api/auth/${provider}/start${suffix}`
}

export function refreshMe(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: getMeQueryKey(), refetchType: "all" })
}
