import { ApiError } from "@/api/fetcher"

export const errorMessage = (cause: unknown): string => {
  if (cause instanceof Error) return cause.message

  return "Something went wrong"
}

export const isUnauthorized = (cause: unknown): boolean => {
  return cause instanceof ApiError && cause.status === 401
}
