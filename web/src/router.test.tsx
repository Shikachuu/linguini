import { QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { render, screen, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vite-plus/test"
import { createAppRouter } from "@/router"
import { server } from "@/test/server"

const renderAt = (path: string) => {
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={router.options.context.queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )

  return router
}

const signedOut = http.get("*/api/me", () => HttpResponse.json({ detail: "Not signed in" }, { status: 401 }))

const config = (google: boolean, apple: boolean) =>
  http.get("*/api/config", () => HttpResponse.json({ providers: { google, apple }, locale: "hu-HU" }))

describe("routing", () => {
  it("sends signed-out visitors to login and keeps where they were going", async () => {
    server.use(signedOut, config(true, false))
    const router = renderAt("/h/h1/recipes")
    const google = await screen.findByRole("link", { name: "Continue with Google" })
    expect(router.state.location.pathname).toBe("/login")
    expect(google).toHaveAttribute("href", "/api/auth/google/start?return_to=%2Fh%2Fh1%2Frecipes")
    expect(screen.queryByRole("link", { name: "Continue with Apple" })).not.toBeInTheDocument()
  })

  it("shows a provider login error passed back to the root", async () => {
    server.use(config(true, true))
    renderAt("/?login_error=invite_required")
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You need an invite link from a household member to create an account.",
    )
    expect(await screen.findByRole("link", { name: "Continue with Apple" })).toBeInTheDocument()
  })

  it("carries an invite code through login", async () => {
    server.use(signedOut, config(true, true))
    renderAt("/invite/abc123")
    const apple = await screen.findByRole("link", { name: "Continue with Apple" })
    expect(apple).toHaveAttribute("href", "/api/auth/apple/start?invite=abc123")
  })

  it("opens the last used household for signed-in users", async () => {
    localStorage.setItem("linguini:last-household", "h2")
    server.use(
      http.get("*/api/me", () =>
        HttpResponse.json({
          id: "u1",
          display_name: "Alice",
          identities: [],
          households: [
            { id: "h1", name: "Home" },
            { id: "h2", name: "Cabin" },
          ],
        }),
      ),
      http.get("*/api/households/h2/threads", () => HttpResponse.json([])),
    )
    const router = renderAt("/")
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/h/h2/chat")
    })
    expect(await screen.findByText("No chats yet.")).toBeInTheDocument()
  })
})
