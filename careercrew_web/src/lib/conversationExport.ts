/** 会话导出（前端）：纯函数构造 Markdown / JSON 文本 + Blob 下载。

镜像后端 careercrew_core/conversation/export.py（§13.2/§13.3）：
- MD：`# Title` → `## User` / `## Assistant`（含 `### Sources`）
- JSON：{thread, messages, sources, runs:[]}（前端历史不含 run 元数据，runs 恒为空数组）
- 不含 token / api_key / system prompt 等敏感字段（前端消息本就不含，仍做白名单）。
*/

export interface ExportSource {
  doc?: string
  source?: string
  score?: number
  text?: string
  image_path?: string
  page?: number | null
}

export interface ExportMessage {
  role: "user" | "assistant"
  content: string
  sources?: ExportSource[]
}

const SENSITIVE_MARKERS = ["system_prompt", "api_key", "token", "secret", "credential"]

function assertNoSensitive(text: string): void {
  const low = text.toLowerCase()
  for (const marker of SENSITIVE_MARKERS) {
    if (low.includes(marker)) {
      throw new Error(`导出内容疑似包含敏感字段「${marker}」，已拒绝导出`)
    }
  }
}

/** 构造 Markdown 文本。 */
export function buildMarkdown(title: string, messages: ExportMessage[]): string {
  const lines: string[] = [`# ${title || "未命名会话"}`, ""]
  for (const m of messages) {
    if (m.role === "user") lines.push("## User")
    else if (m.role === "assistant") lines.push("## Assistant")
    else continue
    lines.push("", m.content, "")
    if (m.role === "assistant" && m.sources?.length) {
      lines.push("### Sources", "")
      for (const s of m.sources) lines.push(`- ${s.doc || s.source || ""}`)
      lines.push("")
    }
  }
  const text = lines.join("\n").trimEnd() + "\n"
  assertNoSensitive(text)
  return text
}

/** 构造 JSON 结构（runs 恒空：前端历史不含 run 元数据）。 */
export interface ConversationJsonExport {
  thread: { title: string }
  messages: Array<{ role: string; content: string; sources?: ExportSource[] }>
  sources: ExportSource[]
  runs: never[]
}

export function buildJson(title: string, messages: ExportMessage[]): ConversationJsonExport {
  const msgs: ConversationJsonExport["messages"] = messages
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => {
      const entry: ConversationJsonExport["messages"][number] = {
        role: m.role,
        content: m.content,
      }
      if (m.role === "assistant" && m.sources?.length) entry.sources = m.sources
      return entry
    })
  const sources: ExportSource[] = []
  for (const m of messages) {
    if (m.role === "assistant" && m.sources?.length) sources.push(...m.sources)
  }
  const body: ConversationJsonExport = { thread: { title }, messages: msgs, sources, runs: [] }
  assertNoSensitive(JSON.stringify(body))
  return body
}

/** 把文本保存为 Blob 并触发下载。 */
export function downloadBlob(content: string, mime: string, filename: string): void {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
