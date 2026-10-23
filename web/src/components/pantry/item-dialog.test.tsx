import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vite-plus/test";
import type { ItemOut } from "@/api/gen/model";
import { ItemDialog } from "@/components/pantry/item-dialog";
import { Button } from "@/components/ui/button";
import { renderWithClient } from "@/test/render";
import { server } from "@/test/server";

const ITEM: ItemOut = {
  id: "i1",
  name: "tej",
  quantity: 2,
  unit: "l",
  dimension: "volume",
  kifli_product_id: null,
  last_purchased_at: null,
  expires_at: "2026-11-02T00:00:00Z",
  notes: "opened",
  updated_at: "2026-10-01T10:00:00Z",
};

describe("ItemDialog", () => {
  it("adds an item with an expiry date", async () => {
    let sent: unknown;
    server.use(
      http.post("*/api/households/h1/items", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(ITEM, { status: 201 });
      }),
    );
    renderWithClient(<ItemDialog hid="h1" trigger={<Button>Add</Button>} />);
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await userEvent.type(screen.getByLabelText("Name"), "tej");
    await userEvent.type(screen.getByLabelText("Amount to add"), "2");
    await userEvent.clear(screen.getByLabelText("Unit"));
    await userEvent.type(screen.getByLabelText("Unit"), "l");
    await userEvent.type(screen.getByLabelText("Expires"), "2026-11-02");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await screen.findByRole("button", { name: "Add" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(sent).toEqual({
      name: "tej",
      quantity: 2,
      unit: "l",
      expires_at: "2026-11-02T00:00:00.000Z",
      notes: null,
    });
  });

  it("shows the server's reason when the unit conflicts", async () => {
    server.use(
      http.patch("*/api/households/h1/items/i1", () =>
        HttpResponse.json({ detail: "tej is measured by volume, not mass" }, { status: 409 }),
      ),
    );
    renderWithClient(<ItemDialog hid="h1" item={ITEM} trigger={<Button>Edit</Button>} />);
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByLabelText("Notes")).toHaveValue("opened");
    await userEvent.clear(screen.getByLabelText("Unit"));
    await userEvent.type(screen.getByLabelText("Unit"), "kg");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("tej is measured by volume, not mass")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
