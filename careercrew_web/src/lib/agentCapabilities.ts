/**
 * Tool Capability API 封装（T3.5 §16）：拉取服务端可见工具 + 客户端选择语义。
 *
 * 后端契约（GET /api/agent/capabilities?module=chat）返回：
 *   {"module":"chat","tools":[{"id":"rag_query","name":"Knowledge Search",
 *                              "enabled":true,"requires_hitl":false}]}
 *
 * 客户端选择 = 本轮允许 Agent 使用哪些 Tool（≠ 立即执行，§16.2）。选择集合随
 * 请求体 tools 提交；服务端按 effective_tools = client ∩ server_allowlist 裁剪，
 * 任何不在 server allowlist 的工具调用都会被拦截（§16.3）。
 */
import { apiFetch } from "@/lib/auth"
import { apiErrorText } from "@/lib/errors"

/** 单个工具 capability（与后端 /api/agent/capabilities 返回对齐）。 */
export interface ToolCapability {
  id: string
  name: string
  enabled: boolean
  requires_hitl: boolean
}

const TOOL_LABEL_FALLBACK: Record<string, string> = {
  rag_query: "Knowledge Search",
  memory_search: "Memory Search",
  memory_write: "Memory Write",
  profile_update: "Profile Update",
  salary_query: "Salary Query",
  read_image: "Read Image",
  search_jobs: "Search Jobs",
}

/** capability 展示名（后端 name 优先，缺失回退本地映射，再回退 id）。 */
export function toolDisplayName(cap: ToolCapability): string {
  if (cap.name && cap.name !== cap.id) return cap.name
  return TOOL_LABEL_FALLBACK[cap.id] ?? cap.id
}

/**
 * 拉取某 module 的服务端可见工具 capability。纯函数，供 picker 与页面复用。
 * 失败抛 Error（已中文化）；调用方自行降级（禁用 picker / 不发送 tools）。
 */
export async function fetchAgentCapabilities(module = "chat"): Promise<ToolCapability[]> {
  const qs = module ? `?module=${encodeURIComponent(module)}` : ""
  const resp = await apiFetch(`/api/agent/capabilities${qs}`)
  if (!resp.ok) throw new Error(await apiErrorText(resp, "加载工具能力失败"))
  const body = (await resp.json()) as { tools?: ToolCapability[] }
  return body.tools ?? []
}

/**
 * 计算最终提交的 tools 选择集合（客户端语义）：
 * 过滤掉 enabled=false 或不在 capability 列表里的 id，保留选中顺序并去重。
 */
export function resolveSelectedToolIds(
  capabilities: ToolCapability[],
  selected: string[],
): string[] {
  const allowed = new Set(
    capabilities.filter((c) => c.enabled).map((c) => c.id),
  )
  const seen = new Set<string>()
  const out: string[] = []
  for (const id of selected) {
    if (allowed.has(id) && !seen.has(id)) {
      seen.add(id)
      out.push(id)
    }
  }
  return out
}
