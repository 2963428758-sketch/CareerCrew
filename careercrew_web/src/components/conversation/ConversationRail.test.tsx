// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ConversationRail, type RailTurn } from "./ConversationRail"

function turn(id: string, content?: string): RailTurn {
  return { id, user: content ? { content } : {} }
}

describe("ConversationRail", () => {
  beforeEach(() => {
    // 稳定视口：少量轮次下方块全部可点；大量轮次用例自己覆写 innerHeight
    window.innerHeight = 800
  })

  describe("条数", () => {
    it("为每条 RailTurn 渲染一个横条 button，aria-label 含问题摘要", () => {
      const turns = [
        turn("t1", "你好，我想请教一下简历怎么写"),
        turn("t2", "面试的时候该怎么自我介绍"),
        turn("t3"),
      ]
      render(<ConversationRail turns={turns} activeTurnId="t1" onSelect={() => {}} />)

      const bars = screen.getAllByRole("button", { name: /跳转到/ })
      expect(bars).toHaveLength(3)
      expect(screen.getByRole("button", { name: "跳转到：你好，我想请教一下简历怎么写" })).toBeTruthy()
      expect(screen.getByRole("button", { name: "跳转到：面试的时候该怎么自我介绍" })).toBeTruthy()
      // 无内容的消息回退为通用标签
      expect(screen.getByRole("button", { name: "跳转到对话" })).toBeTruthy()
    })

    it("无任何 turn 时渲染 null", () => {
      const { container } = render(<ConversationRail turns={[]} activeTurnId={null} onSelect={() => {}} />)
      expect(container.innerHTML).toBe("")
    })
  })

  describe("点击", () => {
    it("点击横条 → onSelect 收到对应 turnId", () => {
      const onSelect = vi.fn()
      const turns = [
        turn("t1", "第一个问题"),
        turn("t2", "第二个问题"),
        turn("t3", "第三个问题"),
      ]
      render(<ConversationRail turns={turns} activeTurnId={null} onSelect={onSelect} />)

      fireEvent.click(screen.getByRole("button", { name: "跳转到：第二个问题" }))
      expect(onSelect).toHaveBeenCalledTimes(1)
      expect(onSelect).toHaveBeenCalledWith("t2")
    })
  })

  describe("active 状态", () => {
    it("active 横条与普通横条样式可区分", () => {
      const turns = [turn("t1", "A"), turn("t2", "B")]
      render(<ConversationRail turns={turns} activeTurnId="t2" onSelect={() => {}} />)

      const inactive = screen.getByRole("button", { name: "跳转到：A" })
        .querySelector("span")
      const active = screen.getByRole("button", { name: "跳转到：B" })
        .querySelector("span")
      // 内层 span 才是视觉横条：active 命中 w-[22px] 宽条样式，非 active 保持 w-[12px]
      expect(active?.className).toContain("w-[22px]")
      expect(inactive?.className).not.toContain("w-[22px]")
    })
  })

  describe("hover 摘要截断", () => {
    it("超过 56 字符的问题摘要截断并追加 …", () => {
      const long = "这是一段很长的问题描述，用来验证超过五十六个字符之后的截断行为以及省略号的追加是否正确，内容要足够长才能触发截断逻辑终点"
      expect(long.length).toBeGreaterThan(56)
      const turns = [turn("t1", long)]
      render(<ConversationRail turns={turns} activeTurnId={null} onSelect={() => {}} />)

      const label = screen.getByRole("button").getAttribute("aria-label") ?? ""
      expect(label).toContain("…")
      // 去掉固定前缀「跳转到：」与尾部省略号后，恰为 56 个字符
      expect(label.replace("跳转到：", "").replace(/…$/, "")).toHaveLength(56)
    })

    it("短于 56 字符的摘要不追加省略号", () => {
      const turns = [turn("t1", "这个问题很短")]
      render(<ConversationRail turns={turns} activeTurnId={null} onSelect={() => {}} />)
      expect(screen.getByRole("button").getAttribute("aria-label")).toBe("跳转到：这个问题很短")
    })
  })

  describe("滑窗 EdgeTick", () => {
    function many(n: number): RailTurn[] {
      return Array.from({ length: n }, (_, i) => turn(`q${i}`, `第 ${i} 个问题`))
    }

    it("少量轮次（n×MIN_ROW ≤ avail）不渲染 EdgeTick", () => {
      const turns = many(20) // 20×4=80 ≤ 400
      render(<ConversationRail turns={turns} activeTurnId={null} onSelect={() => {}} />)
      expect(screen.queryByRole("button", { name: "更早的对话" })).toBeNull()
      expect(screen.queryByRole("button", { name: "更晚的对话" })).toBeNull()
    })

    it("大量轮次进入滑窗：点击「更晚的对话」→ onSelect 收到窗口外第一轮 id", () => {
      window.innerHeight = 800
      const turns = many(160) // 160×4=640 > 400 且 n-cap=112>0 → 滑窗
      const onSelect = vi.fn()
      render(<ConversationRail turns={turns} activeTurnId="q0" onSelect={onSelect} />)

      const later = screen.getByRole("button", { name: "更晚的对话" })
      expect(later).toBeTruthy()

      fireEvent.click(later)
      expect(onSelect).toHaveBeenCalledTimes(1)
      // avail=400, cap=min(48, floor(400/9)=44)=44；activeTurnId="q0"→start=0,end=44
      expect(onSelect.mock.calls[0][0]).toBe("q44")
    })

    it("滑窗且存在更早段：点击「更早的对话」→ onSelect 收到窗口前第一轮 id", () => {
      window.innerHeight = 800
      const turns = many(160)
      const onSelect = vi.fn()
      // activeTurnId 为较晚轮次使 start > 0：start=160-44=116，更早段点击取 turns[115]
      render(<ConversationRail turns={turns} activeTurnId="q159" onSelect={onSelect} />)

      const earlier = screen.getByRole("button", { name: "更早的对话" })
      expect(earlier).toBeTruthy()

      fireEvent.click(earlier)
      expect(onSelect).toHaveBeenCalledTimes(1)
      expect(onSelect.mock.calls[0][0]).toBe("q115")
    })
  })
})
