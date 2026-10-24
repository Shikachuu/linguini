import { z } from "zod"

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

const SAFE_METHODS = new Set(["GET", "HEAD"])

const detailItem = z.union([
  z.object({ msg: z.string() }).transform((item) => item.msg),
  z.json().transform((value) => JSON.stringify(value)),
])

const errorBody = z.object({
  detail: z.union([z.string(), z.array(detailItem).transform((items) => items.join("; "))]),
})

export const detailOf = (text: string): string | undefined => {
  try {
    return errorBody.safeParse(JSON.parse(text)).data?.detail
  } catch {
    return undefined
  }
}

const errorDetail = async (response: Response): Promise<string> => {
  return detailOf(await response.text()) ?? (response.statusText || `HTTP ${response.status}`)
}

export const apiHeaders = (method: string, headers?: HeadersInit): Headers => {
  const result = new Headers(headers)

  if (!SAFE_METHODS.has(method.toUpperCase())) result.set("X-Requested-With", "linguini")

  return result
}

export const apiFetch = async <T>(url: string, init: RequestInit = {}): Promise<T> => {
  const method = init.method ?? "GET"

  const response = await fetch(url, {
    ...init,
    headers: apiHeaders(method, init.headers),
    credentials: "same-origin",
  })

  if (!response.ok) throw new ApiError(response.status, await errorDetail(response))

  const text = await response.text()
  const body: unknown = text === "" ? undefined : JSON.parse(text)

  // SAFETY: orval passes the OpenAPI response schema of this endpoint as T, and FastAPI serializes the response through that schema.
  return body as T
}

export type ErrorType<_E> = ApiError
