/**
 * 会话附件 API 封装（T3.2 §35）：上传/列表/删除/存库/轮询 的纯函数。
 *
 * 后端契约（POST/GET/DELETE /api/chat/attachments，见 routers/attachments.py）：
 * - 状态全集：uploading / uploaded / parsing / ready / failed / deleted / saved_to_knowledge
 * - save-to-knowledge 异步：202 {status:"parsing"}，客户端轮询 GET list 直到终态。
 */
import { apiFetch } from "@/lib/auth"
import { apiErrorText } from "@/lib/errors"

/** 附件状态（§14.3 状态全集）。 */
export type AttachmentStatus =
  | "uploading"
  | "uploaded"
  | "parsing"
  | "ready"
  | "failed"
  | "deleted"
  | "saved_to_knowledge"

/** 附件元数据（GET list 返回的字段）。 */
export interface Attachment {
  id: string
  thread_id: string
  original_filename: string
  mime_type: string
  size_bytes: number
  status: AttachmentStatus
  parser_type?: string | null
  parser_error?: string | null
  knowledge_document_id?: string | null
  created_at: string
  expires_at: string | null
}

/** 与服务端校验（validation.py）对齐的扩展名白名单。 */
export const ATTACHMENT_EXTENSIONS = [
  ".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt", ".png", ".jpg", ".jpeg",
] as const

/** 与服务端一致的单附件大小上限（25MB）。 */
export const MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024

/** 客户端预检：扩展名 + 大小（先于网络请求，避免无谓上传）。 */
export function validateAttachmentSelection(
  name: string,
  sizeBytes: number
): string | null {
  const ext = name.slice(name.lastIndexOf(".")).toLowerCase()
  if (!(ATTACHMENT_EXTENSIONS as readonly string[]).includes(ext)) {
    return `不支持的附件格式：${name}`
  }
  if (sizeBytes > MAX_ATTACHMENT_SIZE) {
    return "附件超过 25MB 限制"
  }
  return null
}

/** 上传单个附件（multipart），返回服务端附件元数据。 */
export async function uploadAttachment(
  threadId: string,
  file: File
): Promise<Attachment> {
  const form = new FormData()
  form.append("thread_id", threadId)
  form.append("file", file)
  const resp = await apiFetch("/api/chat/attachments", {
    method: "POST",
    body: form,
  })
  if (!resp.ok) throw new Error(await apiErrorText(resp, "附件上传失败"))
  return (await resp.json()) as Attachment
}

/** 列出某会话的本人附件。 */
export async function listAttachments(threadId: string): Promise<Attachment[]> {
  const resp = await apiFetch(
    `/api/chat/attachments?thread_id=${encodeURIComponent(threadId)}`
  )
  if (!resp.ok) throw new Error(await apiErrorText(resp, "加载附件失败"))
  return (await resp.json()) as Attachment[]
}

/** 删除附件。 */
export async function deleteAttachment(attachmentId: string): Promise<void> {
  const resp = await apiFetch(
    `/api/chat/attachments/${encodeURIComponent(attachmentId)}`,
    { method: "DELETE" }
  )
  if (!resp.ok) throw new Error(await apiErrorText(resp, "删除附件失败"))
}

/** 请求把附件存入知识库（异步）：202 后由客户端轮询 list 刷新状态。 */
export async function saveAttachmentToKnowledge(
  attachmentId: string
): Promise<void> {
  const resp = await apiFetch(
    `/api/chat/attachments/${encodeURIComponent(attachmentId)}/save-to-knowledge`,
    { method: "POST" }
  )
  if (!resp.ok) throw new Error(await apiErrorText(resp, "存入知识库失败"))
}

/** save-to-knowledge 的终态（解析/入库结束，前端停止轮询）。 */
const TERMINAL_STATUSES: ReadonlySet<AttachmentStatus> = new Set([
  "failed",
  "saved_to_knowledge",
  "deleted",
])

/**
 * 轮询直到附件的 save-to-knowledge 进入终态。
 *
 * 后端把 parse+vectorize+store 合并为一次调用，不再产出可观测的 ready 中间态
 * （ready 仅为 DB 契约保留的过渡值），故终态仅为 failed / saved_to_knowledge /
 * deleted。
 */
export async function pollSaveToKnowledge(
  threadId: string,
  attachmentId: string,
  { intervalMs = 500, timeoutMs = 5 * 60 * 1000 } = {}
): Promise<Attachment> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const items = await listAttachments(threadId)
    const row = items.find((a) => a.id === attachmentId)
    if (row && TERMINAL_STATUSES.has(row.status)) return row
    await new Promise((r) => setTimeout(r, intervalMs))
  }
  throw new Error("解析超时，请检查附件状态后重试")
}
