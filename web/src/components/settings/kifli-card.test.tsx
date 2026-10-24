import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it, vi } from "vite-plus/test"
import { KifliCard } from "@/components/settings/kifli-card"
import { renderWithClient } from "@/test/render"
import { server } from "@/test/server"

const BASE = "*/api/households/h1/kifli"
const CONNECT = {
  authorize_url: "https://shop.example/authorize?state=s",
  redirect_uri: "http://localhost:3334/oauth/callback",
  instructions: "Open the link and sign in, then paste the address here.",
}

describe("KifliCard", () => {
  it("connects through the pasted callback address", async () => {
    let connected = false
    let pasted: unknown
    const open = vi.spyOn(window, "open").mockReturnValue(null)
    server.use(
      http.get(BASE, () => HttpResponse.json({ connected })),
      http.post(`${BASE}/connect`, () => HttpResponse.json(CONNECT)),
      http.post(`${BASE}/callback`, async ({ request }) => {
        pasted = await request.json()
        connected = true
        return HttpResponse.json({ connected: true, connected_at: "2026-10-01T10:00:00Z" })
      }),
    )
    renderWithClient(<KifliCard hid="h1" />)
    await userEvent.click(await screen.findByRole("button", { name: "Connect" }))
    expect(open).toHaveBeenCalledWith(CONNECT.authorize_url, "_blank", "noopener")
    expect(screen.getByText(CONNECT.instructions)).toBeInTheDocument()

    await userEvent.type(
      screen.getByLabelText("Address from the address bar"),
      "http://localhost:3334/oauth/callback?code=c&state=s",
    )
    await userEvent.click(screen.getByRole("button", { name: "Finish connecting" }))
    expect(await screen.findByText("Connected")).toBeInTheDocument()
    expect(pasted).toEqual({ callback_url: "http://localhost:3334/oauth/callback?code=c&state=s" })
  })

  it.each([
    [400, "not a valid or current sign-in result"],
    [401, "Kifli rejected the sign-in"],
    [502, "Kifli could not be reached"],
  ])("explains a %i from the callback", async (status, text) => {
    vi.spyOn(window, "open").mockReturnValue(null)
    server.use(
      http.get(BASE, () => HttpResponse.json({ connected: false })),
      http.post(`${BASE}/connect`, () => HttpResponse.json(CONNECT)),
      http.post(`${BASE}/callback`, () => HttpResponse.json({ detail: "x" }, { status })),
    )
    renderWithClient(<KifliCard hid="h1" />)
    await userEvent.click(await screen.findByRole("button", { name: "Connect" }))
    await userEvent.type(screen.getByLabelText("Address from the address bar"), "http://localhost:3334/oauth/callback")
    await userEvent.click(screen.getByRole("button", { name: "Finish connecting" }))
    expect(await screen.findByText(new RegExp(text))).toBeInTheDocument()
  })
})
