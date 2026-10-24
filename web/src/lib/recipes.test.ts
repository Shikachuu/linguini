import { describe, expect, it } from "vite-plus/test"
import { keyedSteps } from "./recipes"

describe("keyedSteps", () => {
  it("gives repeated steps distinct keys", () => {
    expect(keyedSteps(["Stir", "Wait", "Stir"]).map(({ key }) => key)).toEqual(["Stir#0", "Wait#0", "Stir#1"])
  })
})
