/**
 * 会话搜索纯逻辑：内存索引 + 匹配区间计算 + 前/后循环跳转。
 * 数据纯函数与组件分离，便于单测。只搜索当前会话已加载的 user + assistant 正文，
 * 不涉及 Tool 原始输出 / Prompt / 隐藏元数据（§11.1）。
 */

/** 可搜索消息（扁平索引单元）。 */
export interface SearchableMessage {
  messageId: string
  turnId: string
  text: string
  role: "user" | "assistant"
}

/** 一次匹配区间：messageId 定位消息，start/end 为正文内的 UTF-16 偏移区间（[start, end)）。 */
export interface SearchMatch {
  messageId: string
  start: number
  end: number
}

/** 索引构建入参的最小消息 shape（各页 ChatMsg/ChatMessage 的公共字段）。 */
export interface SearchableSource {
  id: string
  role: "user" | "assistant"
  content?: string
  turnId?: string
}

/**
 * 由扁平消息流构建内存索引：只保留有正文的用户/助手消息；按输入顺序展开。
 * turnId 缺省回退到消息 id（孤儿 assistant 等异常场景）。
 */
export function buildSearchIndex(messages: SearchableSource[]): SearchableMessage[] {
  const index: SearchableMessage[] = []
  for (const m of messages) {
    if (m.role !== "user" && m.role !== "assistant") continue
    const text = m.content ?? ""
    if (!text.trim()) continue
    index.push({
      messageId: m.id,
      turnId: m.turnId ?? m.id,
      text,
      role: m.role,
    })
  }
  return index
}

/** 把关键词转为大小写不敏感的匹配源；空关键词返回 null（无匹配）。 */
function normalizeKeyword(keyword: string): string | null {
  const kw = keyword.trim()
  return kw ? kw.toLowerCase() : null
}

/**
 * 在索引内计算所有匹配区间（大小写不敏感，多次出现全部保留）。
 * 返回顺序与消息顺序、消息内偏移顺序一致（即 DOM 文档顺序）。
 */
export function findMatches(index: SearchableMessage[], keyword: string): SearchMatch[] {
  const kw = normalizeKeyword(keyword)
  if (!kw || kw.length === 0) return []
  const matches: SearchMatch[] = []
  for (const msg of index) {
    const text = msg.text.toLowerCase()
    let from = 0
    for (;;) {
      const at = text.indexOf(kw, from)
      if (at < 0) break
      matches.push({ messageId: msg.messageId, start: at, end: at + kw.length })
      from = at + kw.length
    }
  }
  return matches
}

/** 前/后循环跳转：delta=+1 下一项，-1 上一项；越界回绕。空匹配集返回 -1。 */
export function stepMatch(matches: SearchMatch[], currentIndex: number, delta: 1 | -1): number {
  if (matches.length === 0) return -1
  if (currentIndex < 0 || currentIndex >= matches.length) return 0
  return (currentIndex + delta + matches.length) % matches.length
}

/**
 * 单条消息内的匹配区间（供高亮渲染用）。空/无效关键词返回空数组。
 */
export function matchesInText(text: string, keyword: string): { start: number; end: number }[] {
  const kw = normalizeKeyword(keyword)
  if (!kw || kw.length === 0) return []
  const lower = text.toLowerCase()
  const out: { start: number; end: number }[] = []
  let from = 0
  for (;;) {
    const at = lower.indexOf(kw, from)
    if (at < 0) break
    out.push({ start: at, end: at + kw.length })
    from = at + kw.length
  }
  return out
}
