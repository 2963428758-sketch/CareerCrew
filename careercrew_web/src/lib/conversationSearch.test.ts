import { describe, expect, it } from "vitest"
import { stepMatch } from "@/lib/conversationSearch"

describe("conversationSearch — stepMatch（前/后循环）", () => {
  it("下一项 / 上一项在区间内正常前进后退", () => {
    expect(stepMatch(3, 0, 1)).toBe(1)
    expect(stepMatch(3, 1, 1)).toBe(2)
    expect(stepMatch(3, 2, -1)).toBe(1)
  })

  it("越界回绕", () => {
    expect(stepMatch(3, 2, 1)).toBe(0)
    expect(stepMatch(3, 0, -1)).toBe(2)
  })

  it("空匹配集返回 -1；非法 index 回 0", () => {
    expect(stepMatch(0, 0, 1)).toBe(-1)
    expect(stepMatch(3, 99, 1)).toBe(0)
    expect(stepMatch(3, -5, -1)).toBe(0)
  })
})
