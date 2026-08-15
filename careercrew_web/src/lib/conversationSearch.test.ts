import { describe, expect, it } from "vitest"
import {
  buildSearchIndex,
  findMatches,
  matchesInText,
  stepMatch,
} from "@/lib/conversationSearch"

describe("conversationSearch — buildSearchIndex", () => {
  it("只索引有正文的 user/assistant，忽略空内容与非法 role", () => {
    const idx = buildSearchIndex([
      { id: "u1", role: "user", content: "你好" },
      { id: "a1", role: "assistant", content: "回答" },
      { id: "a2", role: "assistant", content: "" },
      { id: "s1", role: "system", content: "隐藏" },
      { id: "u2", role: "user", content: " " },
    ] as never[])
    expect(idx).toHaveLength(2)
    expect(idx.map((m) => m.messageId)).toEqual(["u1", "a1"])
  })

  it("turnId 缺省回退到 messageId", () => {
    const idx = buildSearchIndex([
      { id: "u1", role: "user", content: "q", turnId: "t1" },
      { id: "a1", role: "assistant", content: "a" },
    ])
    expect(idx[0].turnId).toBe("t1")
    expect(idx[1].turnId).toBe("a1")
  })
})

describe("conversationSearch — findMatches / matchesInText", () => {
  const idx = buildSearchIndex([
    { id: "u1", role: "user", content: "我要找 Apple 和 apple 的工作" },
    { id: "a1", role: "assistant", content: "Apple 很好，apple 也是" },
  ])

  it("大小写不敏感，返回全部出现与正确区间", () => {
    const ms = findMatches(idx, "apple")
    expect(ms).toHaveLength(4)
    expect(ms[0]).toMatchObject({ messageId: "u1", start: 4, end: 9 })
    expect(ms[1]).toMatchObject({ messageId: "u1" })
    expect(ms[2]).toMatchObject({ messageId: "a1", start: 0, end: 5 })
    expect(ms[3]).toMatchObject({ messageId: "a1" })
  })

  it("空 / 空白关键词返回空", () => {
    expect(findMatches(idx, "")).toEqual([])
    expect(findMatches(idx, "   ")).toEqual([])
  })

  it("无匹配返回空数组", () => {
    expect(findMatches(idx, "不存在")).toEqual([])
  })

  it("matchesInText 计算单条消息内区间（大小写不敏感、多次出现）", () => {
    expect(matchesInText("Abc abc ABC", "abc")).toEqual([
      { start: 0, end: 3 },
      { start: 4, end: 7 },
      { start: 8, end: 11 },
    ])
    expect(matchesInText("hello", "zzz")).toEqual([])
  })
})

describe("conversationSearch — stepMatch（前/后循环）", () => {
  const matches = [
    { messageId: "a", start: 0, end: 2 },
    { messageId: "b", start: 0, end: 2 },
    { messageId: "c", start: 0, end: 2 },
  ]

  it("下一项 / 上一项在区间内正常前进后退", () => {
    expect(stepMatch(matches, 0, 1)).toBe(1)
    expect(stepMatch(matches, 1, 1)).toBe(2)
    expect(stepMatch(matches, 2, -1)).toBe(1)
  })

  it("越界回绕", () => {
    expect(stepMatch(matches, 2, 1)).toBe(0)
    expect(stepMatch(matches, 0, -1)).toBe(2)
  })

  it("空匹配集返回 -1；非法 index 回 0", () => {
    expect(stepMatch([], 0, 1)).toBe(-1)
    expect(stepMatch(matches, 99, 1)).toBe(0)
    expect(stepMatch(matches, -5, -1)).toBe(0)
  })
})
