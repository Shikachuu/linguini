import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vite-plus/test"
import { LogoMark, Wordmark } from "@/components/logo"
import { APP_NAME } from "@/lib/brand"

describe("logo", () => {
  it("hides the mark from assistive tech when it has no label", () => {
    const { container } = render(<LogoMark />)
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true")
  })

  it("exposes a labelled mark as an image", () => {
    render(<LogoMark aria-label={APP_NAME} />)
    expect(screen.getByRole("img", { name: APP_NAME })).toBeInTheDocument()
  })

  it("treats an empty label as no label", () => {
    const { container } = render(<LogoMark aria-label="" />)
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true")
  })

  it("renders the app name in the wordmark", () => {
    render(<Wordmark />)
    expect(screen.getByText(APP_NAME)).toBeInTheDocument()
  })
})
