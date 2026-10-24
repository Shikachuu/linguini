import { z, type ZodType } from "zod"

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

export type ApiFetchInit<T> = RequestInit & { schema?: ZodType<T> }

export const apiHeaders = (method: string, headers?: HeadersInit): Headers => {
  const result = new Headers(headers)

  if (!SAFE_METHODS.has(method.toUpperCase())) result.set("X-Requested-With", "linguini")

  return result
}

export const apiFetch = async <T>(url: string, init: ApiFetchInit<T> = {}): Promise<T> => {
  const { schema, ...request } = init
  const method = request.method ?? "GET"

  const response = await fetch(url, {
    ...request,
    headers: apiHeaders(method, request.headers),
    credentials: "same-origin",
  })

  const text = await response.text()

  if (!response.ok) {
    throw new ApiError(response.status, detailOf(text) ?? (response.statusText || `HTTP ${response.status}`))
  }

  const body = schema ?? z.custom<T>((value) => value === undefined)

  return body.parse(text === "" ? undefined : JSON.parse(text))
}

export type ErrorType<_E> = ApiError
