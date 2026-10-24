import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vite-plus/test"
import type { EventOut, RecipeOut } from "@/api/gen/model"
import { CookDialog } from "@/components/recipes/cook-dialog"
import { renderWithClient } from "@/test/render"
import { server } from "@/test/server"

const RECIPE: RecipeOut = {
  id: "00000000-0000-4000-8000-0000000000d1",
  title: "Rizses hus",
  servings: 2,
  ingredients: [{ name: "rizs", quantity: 200, unit: "g", optional: false }],
  steps: [],
  allergens: [],
  source: "manual",
  created_at: "2026-10-01T10:00:00Z",
  updated_at: "2026-10-01T10:00:00Z",
}

const UNDO_EVENT: EventOut = {
  id: "00000000-0000-4000-8000-0000000000f1",
  item_id: "00000000-0000-4000-8000-0000000000c1",
  delta_base: 400,
  quantity_before: 600,
  quantity_after: 1000,
  dimension: "mass",
  unit: "g",
  cause: "undo",
  thread_id: null,
  run_id: null,
  actor_user_id: null,
  undone_by_event_id: null,
  created_at: "2026-10-01T10:00:00Z",
}

describe("CookDialog", () => {
  it("cooks the chosen servings and undoes one ingredient", async () => {
    let cooked: unknown
    let undone = ""
    server.use(
      http.post(
        "*/api/households/00000000-0000-4000-8000-0000000000a1/recipes/00000000-0000-4000-8000-0000000000d1/cook",
        async ({ request }) => {
          cooked = await request.json()

          return HttpResponse.json({
            recipe: RECIPE,
            results: [
              {
                name: "rizs",
                ok: true,
                message: "rizs: 1 kg -> 600 g",
                event_id: "00000000-0000-4000-8000-0000000000e1",
              },
              { name: "csirke", ok: false, message: "csirke: not in the pantry", event_id: null },
            ],
          })
        },
      ),
      http.post("*/api/households/00000000-0000-4000-8000-0000000000a1/events/:eventId/undo", ({ params }) => {
        undone = String(params.eventId)

        return HttpResponse.json({ ...UNDO_EVENT, undone_by_event_id: String(params.eventId) })
      }),
      http.get("*/api/households/00000000-0000-4000-8000-0000000000a1/items", () => HttpResponse.json([])),
      http.get("*/api/households/00000000-0000-4000-8000-0000000000a1/events", () => HttpResponse.json([])),
    )
    renderWithClient(<CookDialog hid="00000000-0000-4000-8000-0000000000a1" recipe={RECIPE} />)
    await userEvent.click(screen.getByRole("button", { name: "Cook" }))
    const servings = screen.getByLabelText("Servings")
    await userEvent.clear(servings)
    await userEvent.type(servings, "4")
    await userEvent.click(screen.getByRole("button", { name: "Cook" }))

    expect(await screen.findByText("rizs: 1 kg -> 600 g")).toBeInTheDocument()
    expect(screen.getByText("csirke: not in the pantry")).toBeInTheDocument()
    expect(cooked).toEqual({ servings: 4 })
    const undoButtons = screen.getAllByRole("button", { name: "Undo" })
    expect(undoButtons).toHaveLength(1)
    await userEvent.click(undoButtons[0])
    expect(await screen.findByText("Undone")).toBeInTheDocument()
    expect(undone).toBe("00000000-0000-4000-8000-0000000000e1")
  })
})
