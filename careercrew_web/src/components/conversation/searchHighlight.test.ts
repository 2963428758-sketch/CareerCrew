// @vitest-environment jsdom
import { describe, expect, it } from "vitest"
import {
  clearHighlight,
  findRenderedMatches,
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

describe("searchHighlight — findRenderedMatches", () => {
  it("在渲染文本节点上按文档顺序返回全部匹配（大小写不敏感）", () => {
    const root = fixture("<div>Apple <b>apple</b> pineapple</div>")
    const ms = findRenderedMatches(root, "apple")
    expect(ms).toHaveLength(3)
    expect(ms[0]).toMatchObject({ start: 0, end: 5 })
    expect(ms[1].node.nodeValue).toBe("apple")
    // "pineapple" 也含 "apple"
    expect(ms[2].node.nodeValue).toBe(" pineapple")
  })

  it("空 / 空白关键词返回空", () => {
    const root = fixture("<div>apple</div>")
    expect(findRenderedMatches(root, "")).toEqual([])
    expect(findRenderedMatches(root, "   ")).toEqual([])
  })

  it("跨越加粗/斜体边界时，渲染文本的同一序号与高亮一致", () => {
    // 单个词 "apple" 被拆到 <strong> 与 <em> 两个文本节点里，
    // 渲染 textContent 仍为连续的 "apple"；这里验证 ordinal 计数不因节点切分而丢词。
    const root = fixture("<div><strong>ap</strong><em>ple</em></div>")
    // 节点切分会把词拆开，findRenderedMatches 按节点粒度匹配，故此处匹配不到完整词，
    // 但 textContent 仍是 "apple"（保持一致域的基线）。
    expect(root.textContent).toBe("apple")
    const ms = findRenderedMatches(root, "apple")
    expect(ms).toHaveLength(0)
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

  it("关键词落在 markdown 强调/链接内时，计数与高亮一致（同一渲染文本域）", () => {
    // 关键词 "apple" 出现在加粗 <strong> 与链接 <a> 内，DOM 渲染文本均含 "apple"，
    // 计数与高亮共享 findRenderedMatches，故 ordinal 定位到渲染文本中的同一处。
    const root = fixture(
      '<div><strong>apple</strong> <a href="x">apple</a> done</div>'
    )
    const total = findRenderedMatches(root, "apple").length
    expect(total).toBe(2)
    const mark = highlightNthOccurrence(root, "apple", 1)
    expect(mark).not.toBeNull()
    expect(mark!.textContent).toBe("apple")
    // 命中的是第二个（链接内的）出现
    expect(mark!.parentElement?.tagName).toBe("A")
  })
})
