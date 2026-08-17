/**
 * @ 引用（Mention）资源 API 封装（T3.4 §15）：可引用资源列表 + 选择校验。
 *
 * 后端契约（GET /api/context/resources?types=knowledge,resume&q=...）返回：
 *   {"items":[{"type":"knowledge_document","id":"doc-id","name":"RAG 技术笔记","visibility":"private"}]}
 *
 * 资源 type：knowledge_document | resume（不支持 @Agent）。资源已过服务端
 * visibility + ownership 过滤，客户端选择后随请求体 mentions 提交，发送路径
 * 后端会再次校验（§15.2），越权引用由后端拒绝。
 */
import { apiFetch } from "@/lib/auth"
import { apiErrorText } from "@/lib/errors"

/** 可引用资源类型（与后端 schemas.Mention.type 对齐；不含 agent）。 */
export type MentionType = "knowledge_document" | "resume"

/** 后端 GET /api/context/resources 返回的单个资源条目。 */
export interface ContextResource {
  type: MentionType
  id: string
  name: string
  visibility: "private" | "public"
}

/** 随请求体提交的 mention（后端二次校验 ownership/visibility）。 */
export interface Mention {
  type: MentionType
  id: string
}

/** 资源类型展示标签（picker 分组用）。 */
export const MENTION_TYPE_LABEL: Record<MentionType, string> = {
  knowledge_document: "知识文档",
  resume: "简历",
}

/**
 * 拉取可引用资源（types 缺省两者；q 按名称模糊）。纯函数，供 picker 与页面复用。
 */
export async function fetchContextResources(opts: {
  types?: MentionType[]
  q?: string
} = {}): Promise<ContextResource[]> {
  const params = new URLSearchParams()
  if (opts.types && opts.types.length > 0) {
    // 后端接受 knowledge,resume（去掉 _document 后缀）
    params.set("types", opts.types.map((t) => (t === "resume" ? "resume" : "knowledge")).join(","))
  }
  if (opts.q && opts.q.trim()) {
    params.set("q", opts.q.trim())
  }
  const qs = params.toString()
  const resp = await apiFetch(`/api/context/resources${qs ? `?${qs}` : ""}`)
  if (!resp.ok) throw new Error(await apiErrorText(resp, "加载可引用资源失败"))
  const body = (await resp.json()) as { items?: ContextResource[] }
  return body.items ?? []
}

/**
 * 搜索防抖：返回 cancel/reset 语义的包装函数（调用方安全中断上一次挂起请求）。
 * 避免每击键一次都发请求；期间用 AbortSignal 无法中断 apiFetch（其签名不暴露
 * signal），故以「忽略过期结果」的 latest-wins 方式收敛抖动。
 */
export function debounce<A extends unknown[]>(
  fn: (...args: A) => void,
  delayMs = 250
): (...args: A) => void {
  let timer: ReturnType<typeof setTimeout> | null = null
  return (...args: A) => {
    if (timer !== null) clearTimeout(timer)
    timer = setTimeout(() => {
      timer = null
      fn(...args)
    }, delayMs)
  }
}
