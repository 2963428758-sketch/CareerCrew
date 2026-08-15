/**
 * DOM 级匹配高亮：在滚动容器内按文档顺序定位第 `ordinal`（0-based）次关键词
 * 出现，并包裹进 <mark class="search-mark">。相比在 React 渲染层对 markdown 源文本
 * 按字符偏移切分，直接作用于已渲染文本节点天然覆盖 UserMessage 纯文本与
 * AssistantMessage/KnowledgeAssistant 的 markdown 富文本（§11 高亮需求）。
 */

/** DOM 文本节点遍历器：按文档顺序产出所有含可见文本的文本节点。 */
export function textNodesIn(root: Node): Text[] {
  const out: Text[] = []
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let node = walker.nextNode()
  while (node) {
    const t = node as Text
    if (t.nodeValue && t.nodeValue.trim().length > 0) out.push(t)
    node = walker.nextNode()
  }
  return out
}

/** 计算每个文本节点内关键词出现的 [start, end) 区间列表（大小写不敏感）。 */
export function rangesInTextNodes(nodes: Text[], keyword: string): { node: Text; ranges: { start: number; end: number }[] }[] {
  const kw = keyword.trim().toLowerCase()
  if (!kw) return []
  const result: { node: Text; ranges: { start: number; end: number }[] }[] = []
  for (const node of nodes) {
    const value = node.nodeValue ?? ""
    const lower = value.toLowerCase()
    const ranges: { start: number; end: number }[] = []
    let from = 0
    for (;;) {
      const at = lower.indexOf(kw, from)
      if (at < 0) break
      ranges.push({ start: at, end: at + kw.length })
      from = at + kw.length
    }
    if (ranges.length) result.push({ node, ranges })
  }
  return result
}

/**
 * 把关键词的第 `ordinal` 次出现包裹进 <mark>，返回该 mark 元素（供 scrollIntoView）。
 * 已存在的旧 mark 先被还原为纯文本（幂等重跑）。找不到（ordinal 越界）返回 null。
 */
export function highlightNthOccurrence(root: Node, keyword: string, ordinal: number): HTMLElement | null {
  // 先还原上次的高亮，避免重复/错位
  clearHighlight(root)

  const kw = keyword.trim().toLowerCase()
  if (!kw || ordinal < 0) return null

  const nodes = textNodesIn(root)
  let seen = 0
  for (const node of nodes) {
    const value = node.nodeValue ?? ""
    const lower = value.toLowerCase()
    let from = 0
    for (;;) {
      const at = lower.indexOf(kw, from)
      if (at < 0) break
      if (seen === ordinal) {
        return wrapRange(node, at, at + kw.length)
      }
      seen++
      from = at + kw.length
    }
  }
  return null
}

/** 把某文本节点的 [start, end) 区间替换为 <mark>，返回 mark 元素。 */
function wrapRange(node: Text, start: number, end: number): HTMLElement {
  const value = node.nodeValue ?? ""
  const before = document.createTextNode(value.slice(0, start))
  const mark = document.createElement("mark")
  mark.className = "search-mark"
  mark.setAttribute("data-search-current", "true")
  mark.textContent = value.slice(start, end)
  const after = document.createTextNode(value.slice(end))
  const parent = node.parentNode
  if (!parent) {
    // 无父节点（异常）：返回空 mark，调用方按 null 处理
    return mark
  }
  parent.insertBefore(before, node)
  parent.insertBefore(mark, node)
  parent.insertBefore(after, node)
  parent.removeChild(node)
  return mark
}

/** 还原容器内所有 search-mark 为纯文本（保持文档顺序）。 */
export function clearHighlight(root: Node): void {
  if (!(root instanceof Element)) return
  const marks = Array.from(root.querySelectorAll("mark.search-mark"))
  for (const mark of marks) {
    const parent = mark.parentNode
    if (!parent) continue
    parent.replaceChild(document.createTextNode(mark.textContent ?? ""), mark)
  }
}

/** 合并相邻文本节点（mark 还原后可能产生碎片），保持 DOM 整洁。 */
export function normalizeTextNodes(root: Node): void {
  root.normalize()
}
