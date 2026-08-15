// @vitest-environment jsdom
import { describe, expect, it } from "vitest"
import {
  clearHighlight,
  highlightNthOccurrence,
  rangesInTextNodes,
  textNodesIn,
} from "@/components/conversation/searchHighlight"

function fixture(html: string): HTMLElement {
  const root = document.createElement("div")
  root.innerHTML = html
  document.body.appendChild(root)
  return root
}

describe("searchHighlight — textNodesIn / rangesInTextNodes", () => {
  it("遍历所有含可见文本的文本节点", () => {
    const root = fixture("<div>hello <b>world</b></div>")
    const nodes = textNodesIn(root)
    expect(nodes.map((n) => n.nodeValue?.trim())).toEqual(["hello", "world"])
  })

  it("大小写不敏感地计算区间", () => {
    const root = fixture("<div>Ab ab AB</div>")
    const nodes = textNodesIn(root)
    const rs = rangesInTextNodes(nodes, "ab")
    expect(rs).toHaveLength(1)
    expect(rs[0].ranges).toEqual([
      { start: 0, end: 2 },
      { start: 3, end: 5 },
      { start: 6, end: 8 },
    ])
  })
})

describe("searchHighlight — highlightNthOccurrence", () => {
  it("高亮第 ordinal 次出现并返回 mark", () => {
    const root = fixture("<div>one two two</div>")
    const mark = highlightNthOccurrence(root, "two", 1)
    expect(mark).not.toBeNull()
    expect(mark!.textContent).toBe("two")
    expect(root.querySelector("mark.search-mark")).toBe(mark)
    expect(root.textContent).toBe("one two two")
  })

  it("ordinal 越界返回 null，且不残留 mark", () => {
    const root = fixture("<div>one two</div>")
    expect(highlightNthOccurrence(root, "two", 5)).toBeNull()
    expect(root.querySelectorAll("mark.search-mark")).toHaveLength(0)
  })

  it("重跑先还原旧 mark（幂等）", () => {
    const root = fixture("<div>a b a</div>")
    highlightNthOccurrence(root, "a", 0)
    const mark = highlightNthOccurrence(root, "a", 1)
    expect(root.querySelectorAll("mark.search-mark")).toHaveLength(1)
    expect(mark!.textContent).toBe("a")
    expect(root.textContent).toBe("a b a")
  })

  it("clearHighlight 还原全部 mark 为纯文本", () => {
    const root = fixture("<div>foo bar</div>")
    highlightNthOccurrence(root, "foo", 0)
    clearHighlight(root)
    expect(root.querySelectorAll("mark.search-mark")).toHaveLength(0)
    expect(root.textContent).toBe("foo bar")
  })
})
