import { afterEach, describe, expect, it, vi } from "vite-plus/test"
import { ApiError, apiFetch } from "./fetcher"

const stubFetch = (response: Response) => {
  const spy = vi.fn<typeof fetch>().mockResolvedValue(response)
  vi.stubGlobal("fetch", spy)

  return spy
}

const sentHeaders = (spy: ReturnType<typeof stubFetch>): Headers => {
  return new Headers(spy.mock.calls[0]?.[1]?.headers)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("apiFetch", () => {
  it("omits the CSRF header on GET", async () => {
    const spy = stubFetch(Response.json({ ok: true }))
    await expect(apiFetch("/api/me")).resolves.toEqual({ ok: true })
    expect(sentHeaders(spy).has("X-Requested-With")).toBe(false)
    expect(spy.mock.calls[0]?.[1]?.credentials).toBe("same-origin")
  })

  it("sends the CSRF header on mutations", async () => {
    const spy = stubFetch(new Response(null, { status: 204 }))
    await expect(apiFetch("/api/me", { method: "DELETE" })).resolves.toBeUndefined()
    expect(sentHeaders(spy).get("X-Requested-With")).toBe("linguini")
  })

  it("raises FastAPI string details as ApiError", async () => {
    stubFetch(Response.json({ detail: "This thread is already answering" }, { status: 409 }))
    const request = apiFetch("/x", { method: "POST" })

    await expect(request).rejects.toBeInstanceOf(ApiError)
    await expect(request).rejects.toMatchObject({ status: 409, message: "This thread is already answering" })
  })

  it("joins validation error messages", async () => {
    stubFetch(Response.json({ detail: [{ msg: "too long" }, { msg: "missing" }] }, { status: 422 }))
    await expect(apiFetch("/x")).rejects.toMatchObject({
      status: 422,
      message: "too long; missing",
    })
  })

  it("falls back to the status text for non-JSON errors", async () => {
    stubFetch(new Response("boom", { status: 502, statusText: "Bad Gateway" }))
    await expect(apiFetch("/x")).rejects.toMatchObject({ status: 502, message: "Bad Gateway" })
  })
})
