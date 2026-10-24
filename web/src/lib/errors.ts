import { ApiError } from "@/api/fetcher"

export const errorMessage = (error: unknown): string => {
  if (error instanceof Error) return error.message

  return "Something went wrong"
}

export const isUnauthorized = (error: unknown): boolean => {
  return error instanceof ApiError && error.status === 401
}
