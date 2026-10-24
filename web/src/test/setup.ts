/// <reference types="@testing-library/jest-dom/vitest" />
import {
  toBeDisabled,
  toBeEnabled,
  toBeInTheDocument,
  toHaveAttribute,
  toHaveTextContent,
  toHaveValue,
} from "@testing-library/jest-dom/matchers"
import { cleanup } from "@testing-library/react"
import { afterAll, afterEach, beforeAll, expect, vi } from "vite-plus/test"
import { server } from "./server"

expect.extend({ toBeDisabled, toBeEnabled, toBeInTheDocument, toHaveAttribute, toHaveTextContent, toHaveValue })

class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

vi.stubGlobal("ResizeObserver", NoopResizeObserver)

vi.stubGlobal("scrollTo", () => {})

vi.stubGlobal("matchMedia", (query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener: () => {},
  removeEventListener: () => {},
  addListener: () => {},
  removeListener: () => {},
  dispatchEvent: () => false,
}))

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" })
})

afterEach(() => {
  cleanup()
  server.resetHandlers()
})

afterAll(() => {
  server.close()
})
