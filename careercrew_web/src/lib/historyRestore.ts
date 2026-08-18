import { apiFetch } from "@/lib/auth"
import { notifyError } from "@/lib/toastBus"
import type { MessageAttachment } from "@/types"

/**
 * 恢复线程历史（§37 状态恢复）的共享解析逻辑，六个对话页共用。
 *
 * 恢复路径迁移（T1.3 brief 决策 2）：
 *  1. 先读 `GET /api/threads/{tid}/messages`（conversation 表，Source of Truth）——
 *     非空时返回带稳定 ID（message_id/turn_id/run_id）的消息；
 *  2. 为空（旧线程 / 无 conversation 记录）→ 回退 `GET /api/memory?thread_id=`（episodic，
 *     无稳定 ID，可接受）。
 *
 * 两种来源统一成同一形状 RestoredMessage（含可选稳定 ID 与 metadata 富结构）。
 */

/** 一条恢复出的消息（来源无关的统一形状）。 */
export interface RestoredMessage {
  role: "user" | "assistant"
  content: string
  /** 后端稳定 message_id（仅 messages 端点来源有；memory 回退为 undefined）。 */
  messageId?: string
  turnId?: string
  runId?: string
  /** assistant 富结构（sources / opinions / calls 等），仅 messages 端点来源有。 */
  metadata?: Record<string, unknown> | null
  /** 用户消息 metadata 中的附件摘要，不包含附件正文。 */
  attachments?: MessageAttachment[]
  /** 原始消息对象（页面可按需读取额外字段，如 legacy memory 的 sources/consult_calls）。 */
  raw?: Record<string, unknown>
}

/** GET /api/threads/{tid}/messages 的返回项。 */
interface ThreadMessage {
  id?: string
  turn_id?: string
  role?: string
  content?: string
  run_id?: string
  metadata?: Record<string, unknown> | null
  [key: string]: unknown
}

function parseAttachmentSummaries(metadata: unknown): MessageAttachment[] | undefined {
  if (!metadata || typeof metadata !== "object") return undefined
  const raw = (metadata as Record<string, unknown>).attachments
  if (!Array.isArray(raw)) return undefined

  const parsed = raw.flatMap((item): MessageAttachment[] => {
    if (!item || typeof item !== "object") return []
    const row = item as Record<string, unknown>
    const id = String(row.id ?? "").trim()
    const filename = String(row.filename ?? row.original_filename ?? "").trim()
    if (!id || !filename) return []

    const sizeValue = row.sizeBytes ?? row.size_bytes
    const sizeBytes = typeof sizeValue === "number" && Number.isFinite(sizeValue)
      ? sizeValue
      : undefined
    const mimeValue = row.mimeType ?? row.mime_type
    const mimeType = typeof mimeValue === "string" && mimeValue ? mimeValue : undefined
    const kind = typeof row.kind === "string" && row.kind ? row.kind : undefined
    return [{ id, filename, sizeBytes, mimeType, kind }]
  })
  return parsed.length > 0 ? parsed : undefined
}

/** 把 messages 端点返回解析为统一形状；无效/无内容项跳过。 */
export function parseThreadMessages(rows: unknown[]): RestoredMessage[] {
  const out: RestoredMessage[] = []
  for (const row of rows) {
    if (!row || typeof row !== "object") continue
    const m = row as ThreadMessage
    const role = m.role === "user" || m.role === "assistant" ? m.role : null
    const content = String(m.content ?? "")
    if (!role || !content) continue
    out.push({
      role,
      content,
      messageId: m.id,
      turnId: m.turn_id,
      runId: m.run_id,
      metadata: m.metadata ?? null,
      attachments: parseAttachmentSummaries(m.metadata),
      raw: m,
    })
  }
  return out
}

/** 把 /api/memory 的 episodic 条目解析为统一形状（无稳定 ID）。 */
export function parseMemoryEntries(entries: unknown[]): RestoredMessage[] {
  const out: RestoredMessage[] = []
  for (const entry of entries) {
    if (!entry || typeof entry !== "object") continue
    const e = entry as Record<string, unknown>
    const type = String(e.type || "")
    const content = String(e.content || "")
    if (type === "user_message" && content) {
      out.push({
        role: "user",
        content,
        attachments: parseAttachmentSummaries(e.metadata),
        raw: e,
      })
    } else if (type === "agent_response" && content) {
      out.push({ role: "assistant", content, raw: e })
    }
  }
  return out
}

/**
 * 恢复线程历史：优先 messages 端点（稳定 ID），空时回退 memory。
 * 两类端点任一失败都返回空数组（调用方据此显示空态，不抛错）；
 * 两个端点都失败（网络/服务异常）时弹全局错误提示，避免用户误以为会话本就为空。
 *
 * @param opts.fallbackToMemory 消息端点为空的回退开关：默认 true（历史线程/无
 * conversation 记录时回退 episodic）；主动清空会话后必须传 false——否则会把
 * episodic 记忆里的旧消息捞回来，造成「清空无效」。
 */
export async function restoreHistory(
  tid: string,
  opts: { fallbackToMemory?: boolean } = {}
): Promise<RestoredMessage[]> {
  const fallbackToMemory = opts.fallbackToMemory !== false
  let firstFailed = false
  try {
    const resp = await apiFetch(`/api/threads/${encodeURIComponent(tid)}/messages`)
    if (resp.ok) {
      const rows: unknown = await resp.json()
      const msgs = parseThreadMessages(Array.isArray(rows) ? rows : [])
      if (msgs.length > 0) return msgs
      if (!fallbackToMemory) return []
    } else if (resp.status !== 404) {
      firstFailed = true
    }
  } catch {
    firstFailed = true
  }
  try {
    const resp = await apiFetch(`/api/memory?thread_id=${encodeURIComponent(tid)}`)
    if (!resp.ok) {
      if (firstFailed) notifyError("会话历史加载失败，请刷新页面重试")
      return []
    }
    const entries: unknown = await resp.json()
    return parseMemoryEntries(Array.isArray(entries) ? entries : [])
  } catch {
    if (firstFailed) notifyError("会话历史加载失败，请刷新页面重试")
    return []
  }
}
