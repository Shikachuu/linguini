import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ThemeProvider } from "next-themes"
import { afterEach, describe, expect, it } from "vite-plus/test"
import { ThemePicker } from "@/components/theme-picker"

const renderPicker = () => {
  render(
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <ThemePicker />
    </ThemeProvider>,
  )
}

describe("ThemePicker", () => {
  afterEach(() => {
    localStorage.clear()
    document.documentElement.className = ""
  })

  it("follows the system theme by default", () => {
    renderPicker()
    expect(screen.getByRole("button", { name: "System" })).toHaveAttribute("aria-pressed", "true")
    expect(document.documentElement.classList.contains("dark")).toBe(false)
  })

  it("switches to dark and remembers the choice", async () => {
    renderPicker()
    await userEvent.click(screen.getByRole("button", { name: "Dark" }))
    expect(screen.getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "true")
    expect(document.documentElement.classList.contains("dark")).toBe(true)
    expect(localStorage.getItem("theme")).toBe("dark")
  })

  it("restores a stored theme and returns to the system theme", async () => {
    localStorage.setItem("theme", "light")
    renderPicker()
    expect(screen.getByRole("button", { name: "Light" })).toHaveAttribute("aria-pressed", "true")
    await userEvent.click(screen.getByRole("button", { name: "System" }))
    expect(screen.getByRole("button", { name: "System" })).toHaveAttribute("aria-pressed", "true")
    expect(localStorage.getItem("theme")).toBe("system")
  })
})
