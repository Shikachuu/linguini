import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vite-plus/test";
import { Confirm } from "@/components/confirm";
import { Button } from "@/components/ui/button";

describe("Confirm", () => {
  it("keeps the action disabled until the confirmation text is typed", async () => {
    const onConfirm = vi.fn();
    render(
      <Confirm
        trigger={<Button>Delete account</Button>}
        title="Delete your account?"
        description="This cannot be undone."
        action="Delete for good"
        typeToConfirm="delete my account"
        onConfirm={onConfirm}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Delete account" }));
    const action = screen.getByRole("button", { name: "Delete for good" });
    expect(action).toBeDisabled();
    await userEvent.type(
      screen.getByLabelText("Type delete my account to confirm"),
      "delete my account",
    );
    expect(action).toBeEnabled();
    await userEvent.click(action);
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});
