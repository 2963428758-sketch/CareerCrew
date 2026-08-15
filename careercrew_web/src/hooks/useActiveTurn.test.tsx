// @vitest-environment jsdom
import { renderHook, act } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { RefObject } from "react"
import { useActiveTurn } from "./useActiveTurn"

/** 在 scrollRef 容器内，为每个 id 放一个带 data-turn-anchor 的锚点元素 */
function mountAnchors(ids: string[]) {
  const root = document.createElement("div")
  document.body.appendChild(root)
  for (const id of ids) {
    const el = document.createElement("div")
    el.dataset.turnAnchor = id
    root.appendChild(el)
  }
  return root
}

const originIntersectionObserver = globalThis.IntersectionObserver

/** 捕获 IntersectionObserver 实例（含构造回调），便于测试断言 disconnect、手动触发回调 */
function mockIntersectionObserver() {
  const instances: Array<IntersectionObserver & { trigger: () => void }> = []
  const MockIO = class {
    readonly root = null
    readonly rootMargin = ""
    readonly thresholds: number[] = []
    observe = vi.fn()
    unobserve = vi.fn()
    disconnect = vi.fn()
    takeRecords = vi.fn(() => [])
    constructor(callback: IntersectionObserverCallback) {
      const instance = this as unknown as IntersectionObserver & { trigger: () => void }
      instance.trigger = () => callback([], instance)
      instances.push(instance)
    }
  }
  globalThis.IntersectionObserver = MockIO as unknown as typeof IntersectionObserver
  return { instances }
}

afterEach(() => {
  vi.useRealTimers()
  globalThis.IntersectionObserver = originIntersectionObserver
  document.body.innerHTML = ""
})

describe("useActiveTurn", () => {
  describe("jsdom 兜底（无 IntersectionObserver）", () => {
    it("默认激活最后一个 id", () => {
      const root = mountAnchors(["a", "b", "c"])
      const ref: RefObject<HTMLElement | null> = { current: root }
      const { result } = renderHook(() => useActiveTurn(["a", "b", "c"], ref))
      expect(result.current.activeId).toBe("c")
    })

    it("ids 为空时 activeId 为 null", () => {
      const root = mountAnchors([])
      const ref: RefObject<HTMLElement | null> = { current: root }
      const { result } = renderHook(() => useActiveTurn([], ref))
      expect(result.current.activeId).toBeNull()
    })
  })

  describe("IntersectionObserver（几何规则）", () => {
    let instances: Array<IntersectionObserver & { trigger: () => void }>
    beforeEach(() => {
      instances = mockIntersectionObserver().instances
    })

    it("手动 select(id) 立即激活", () => {
      const root = mountAnchors(["a", "b"])
      const ref: RefObject<HTMLElement | null> = { current: root }
      const { result } = renderHook(() => useActiveTurn(["a", "b"], ref))
      expect(result.current.activeId).toBe("a")
      act(() => result.current.select("b"))
      expect(result.current.activeId).toBe("b")
    })

    it("选中目标仍在视口内时，settle 后保持手动选择", () => {
      vi.useFakeTimers()
      const root = mountAnchors(["a", "b"])
      const elB = root.querySelector('[data-turn-anchor="b"]') as HTMLElement
      // 元素 b 位于容器视口内部（top 500 ~ bottom 520）
      vi.spyOn(elB, "getBoundingClientRect").mockReturnValue({
        x: 0, y: 0, top: 500, bottom: 520, left: 0, right: 100,
        width: 100, height: 20, toJSON: () => ({}),
      } as DOMRect)
      // 容器视口高 800：参考线带也位于 b 之上之外，b 判定为仍可见
      vi.spyOn(root, "getBoundingClientRect").mockReturnValue({
        x: 0, y: 0, top: 0, bottom: 800, left: 0, right: 400,
        width: 400, height: 800, toJSON: () => ({}),
      } as DOMRect)
      const ref: RefObject<HTMLElement | null> = { current: root }
      const { result } = renderHook(() => useActiveTurn(["a", "b"], ref))

      act(() => result.current.select("b"))
      expect(result.current.activeId).toBe("b")

      act(() => { vi.advanceTimersByTime(200) })
      expect(result.current.activeId).toBe("b")
    })

    it("选中目标滚出视口时，settle 后交还几何规则，且 cleanup 断开 observer", () => {
      vi.useFakeTimers()
      const root = mountAnchors(["a", "b", "c"])
      const elB = root.querySelector('[data-turn-anchor="b"]') as HTMLElement
      vi.spyOn(elB, "getBoundingClientRect").mockReturnValue({
        x: 0, y: 0, top: -10000, bottom: -9980, left: 0, right: 100,
        width: 100, height: 20, toJSON: () => ({}),
      } as DOMRect)
      const ref: RefObject<HTMLElement | null> = { current: root }
      const { result, unmount } = renderHook(() => useActiveTurn(["a", "b", "c"], ref))

      act(() => result.current.select("b"))
      expect(result.current.activeId).toBe("b")

      act(() => { vi.advanceTimersByTime(200) })
      expect(result.current.activeId).not.toBe("b")

      unmount()
      expect(instances[0].disconnect).toHaveBeenCalled()
    })

    it("参考线穿越触发重算：激活 top 最接近且不超过 root.top+108 的 turn", () => {
      const root = mountAnchors(["a", "b"])
      // 参考线 lineTop = root.top(0) + 108 = 108
      const elA = root.querySelector('[data-turn-anchor="a"]') as HTMLElement
      const elB = root.querySelector('[data-turn-anchor="b"]') as HTMLElement
      // a 在参考线之上（top 200 > 108），b 在参考线之下（top 90 ≤ 108）
      vi.spyOn(elA, "getBoundingClientRect").mockReturnValue({
        x: 0, y: 0, top: 200, bottom: 220, left: 0, right: 100,
        width: 100, height: 20, toJSON: () => ({}),
      } as DOMRect)
      vi.spyOn(elB, "getBoundingClientRect").mockReturnValue({
        x: 0, y: 0, top: 90, bottom: 110, left: 0, right: 100,
        width: 100, height: 20, toJSON: () => ({}),
      } as DOMRect)
      const ref: RefObject<HTMLElement | null> = { current: root }
      const { result } = renderHook(() => useActiveTurn(["a", "b"], ref))

      // 初始强制重算：b 是唯一「top ≤ 108」的 turn
      expect(result.current.activeId).toBe("b")

      // 穿越回调触发：几何规则保持不变（b 仍最接近参考线且在下）
      act(() => instances[0].trigger())
      expect(result.current.activeId).toBe("b")
    })

    it("所有 top 都在参考线之上时回退到第一个 turn（first）", () => {
      const root = mountAnchors(["a", "b"])
      const elA = root.querySelector('[data-turn-anchor="a"]') as HTMLElement
      const elB = root.querySelector('[data-turn-anchor="b"]') as HTMLElement
      // lineTop = 108；两个 turn 的 top 都大于 108 → 无 above，回退 first（top 最小即 a）
      vi.spyOn(elA, "getBoundingClientRect").mockReturnValue({
        x: 0, y: 0, top: 300, bottom: 320, left: 0, right: 100,
        width: 100, height: 20, toJSON: () => ({}),
      } as DOMRect)
      vi.spyOn(elB, "getBoundingClientRect").mockReturnValue({
        x: 0, y: 0, top: 400, bottom: 420, left: 0, right: 100,
        width: 100, height: 20, toJSON: () => ({}),
      } as DOMRect)
      const ref: RefObject<HTMLElement | null> = { current: root }
      const { result } = renderHook(() => useActiveTurn(["a", "b"], ref))

      expect(result.current.activeId).toBe("a")

      act(() => instances[0].trigger())
      expect(result.current.activeId).toBe("a")
    })
  })
})
