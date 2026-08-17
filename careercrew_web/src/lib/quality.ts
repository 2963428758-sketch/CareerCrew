import { apiFetch } from "@/lib/auth"
import { networkErrorText } from "@/lib/errors"

export const REVIEW_ROOT_CAUSES = [
  "llm", "prompt", "rag_retrieval", "reranker", "tool",
  "context", "ambiguous_question", "product_bug", "unknown",
] as const
export type ReviewRootCause = (typeof REVIEW_ROOT_CAUSES)[number]

export const REVIEW_STATUSES = ["new", "triaged", "fixed", "ignored", "promoted_to_eval"] as const
export type ReviewStatus = (typeof REVIEW_STATUSES)[number]

export const EVAL_STATUSES = ["draft", "approved", "deprecated"] as const
export type EvalStatus = (typeof EVAL_STATUSES)[number]

export const REVIEW_STATUS_LABELS: Record<ReviewStatus, string> = {
  new: "未处理", triaged: "已分诊", fixed: "已修复", ignored: "已忽略", promoted_to_eval: "已入评估集",
}
export const ROOT_CAUSE_LABELS: Record<ReviewRootCause, string> = {
  llm: "模型本身", prompt: "提示词", rag_retrieval: "检索召回", reranker: "重排",
  tool: "工具调用", context: "上下文不足", ambiguous_question: "问题歧义",
  product_bug: "产品缺陷", unknown: "未知",
}

export interface QualityMetrics {
  runs: number
  feedback_count: number
  positive_count: number
  negative_count: number
  helpful_rate: number | null
  feedback_coverage: number | null
  negative_reason_distribution: Record<string, number>
  rag_failure_share: number | null
  tool_failure_share: number | null
  median_latency_ms: number | null
  p95_latency_ms: number | null
  latency_n: number
  avg_input_tokens: number | null
  avg_output_tokens: number | null
  unversioned_run_count: number
  unversioned_run_rate: number | null
  helpful_rate_by_prompt_version: { prompt_version: string; positive_count: number; feedback_count: number; rate: number | null }[]
}

export interface BadCase {
  feedback_id: string
  run_id: string
  reason: string
  share_context: boolean
  created_at: string
  updated_at: string
  module: string
  agent_id: string
  model: string
  prompt_version: string
  agent_version: string
  status: string
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
  latency_ms: number | null
  error_type: string | null
  error_code: string | null
  review_status: ReviewStatus | null
  root_cause: ReviewRootCause | null
  snapshot_available: boolean
}

export interface ReviewRow {
  id: string
  feedback_id: string
  reviewer_user_id: string
  root_cause: ReviewRootCause | null
  review_status: ReviewStatus
  reviewer_note: string | null
  created_at: string
  updated_at: string
}

export interface SnapshotRow {
  snapshot_id: string
  snapshot_json: { messages: { role: string; content: string; turn_id: string; message_id: string }[] }
  redaction_version: string
  redaction_count: number
  expires_at: string
  created_at: string
}

export interface EvalCase {
  id: string
  source_feedback_id: string
  status: EvalStatus
  target_agent: string
  input_text: string
  context: { messages: { role: string; content: string; turn_id: string; message_id: string }[] } | null
  expected_behavior: string | null
  rubric: Record<string, unknown>
  failure_reason: string | null
  source_model: string | null
  source_prompt_version: string | null
  source_agent_version: string | null
  created_by: string
  approved_by: string | null
  created_at: string
  approved_at: string | null
}

interface ErrorResponse { detail?: unknown }
const errText = (_status: number, body: ErrorResponse, fallback: string) =>
  typeof body?.detail === "string" ? body.detail : fallback

export async function fetchQualityMetrics(
  params: { from?: string; to?: string; module?: string; agent?: string; model?: string; prompt_version?: string; agent_version?: string } = {}
): Promise<QualityMetrics> {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value) search.set(key, value)
  })
  const query = search.toString() ? `?${search}` : ""
  try {
    const response = await apiFetch(`/api/quality/metrics${query}`)
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as ErrorResponse
      throw new Error(errText(response.status, body, "加载质检指标失败"))
    }
    return (await response.json()) as QualityMetrics
  } catch (error) {
    throw new Error(networkErrorText(error, "质检指标加载失败，请检查网络"))
  }
}

export async function fetchBadCases(): Promise<BadCase[]> {
  try {
    const response = await apiFetch("/api/quality/bad-cases")
    if (!response.ok) throw new Error("加载坏例列表失败")
    const rows = (await response.json()) as BadCase[]
    if (!Array.isArray(rows)) throw new Error("坏例响应格式无效")
    return rows
  } catch (error) {
    throw new Error(networkErrorText(error, "坏例列表加载失败，请检查网络"))
  }
}

export async function fetchBadCase(feedbackId: string): Promise<BadCase> {
  const response = await apiFetch(`/api/quality/bad-cases/${encodeURIComponent(feedbackId)}`)
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ErrorResponse
    throw new Error(errText(response.status, body, "坏例不存在或无权访问"))
  }
  return (await response.json()) as BadCase
}

export async function fetchReview(feedbackId: string): Promise<ReviewRow | null> {
  const response = await apiFetch(`/api/quality/bad-cases/${encodeURIComponent(feedbackId)}/review`)
  if (response.status === 404) return null
  if (!response.ok) throw new Error("加载归因记录失败")
  return (await response.json()) as ReviewRow
}

export async function putReview(
  feedbackId: string,
  request: { root_cause?: ReviewRootCause | "" | null; status: ReviewStatus; note?: string | "" | null }
): Promise<ReviewRow> {
  const response = await apiFetch(`/api/quality/bad-cases/${encodeURIComponent(feedbackId)}/review`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...(request.root_cause !== undefined ? { root_cause: request.root_cause } : {}),
      status: request.status,
      ...(request.note !== undefined ? { note: request.note } : {}),
    }),
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ErrorResponse
    throw new Error(errText(response.status, body, "保存归因失败"))
  }
  return (await response.json()) as ReviewRow
}

export async function fetchSnapshot(feedbackId: string): Promise<SnapshotRow> {
  const response = await apiFetch(`/api/quality/bad-cases/${encodeURIComponent(feedbackId)}/snapshot`)
  if (response.status === 404) {
    const body = (await response.json().catch(() => ({}))) as ErrorResponse
    throw new Error(errText(404, body, "上下文快照不存在或已过期"))
  }
  if (!response.ok) throw new Error("加载上下文快照失败")
  return (await response.json()) as SnapshotRow
}

export async function promoteToEval(feedbackId: string): Promise<EvalCase> {
  const response = await apiFetch(`/api/quality/bad-cases/${encodeURIComponent(feedbackId)}/promote`, {
    method: "POST",
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ErrorResponse
    throw new Error(errText(response.status, body, "转评估失败"))
  }
  return (await response.json()) as EvalCase
}

export async function fetchEvalCases(status?: EvalStatus): Promise<EvalCase[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ""
  const response = await apiFetch(`/api/quality/eval-cases${query}`)
  if (!response.ok) throw new Error("加载评估集失败")
  return (await response.json()) as EvalCase[]
}

export async function putEvalCase(
  caseId: string,
  fields: Partial<Pick<EvalCase, "status" | "target_agent" | "input_text" | "expected_behavior" | "failure_reason">> & { rubric?: Record<string, unknown> }
): Promise<EvalCase> {
  const response = await apiFetch(`/api/quality/eval-cases/${encodeURIComponent(caseId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ErrorResponse
    throw new Error(errText(response.status, body, "保存评估用例失败"))
  }
  return (await response.json()) as EvalCase
}

export async function approveEvalCase(caseId: string): Promise<EvalCase> {
  const response = await apiFetch(`/api/quality/eval-cases/${encodeURIComponent(caseId)}/approve`, {
    method: "POST",
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ErrorResponse
    throw new Error(errText(response.status, body, "审批失败"))
  }
  return (await response.json()) as EvalCase
}

export async function exportEvalCases(): Promise<string> {
  const response = await apiFetch("/api/quality/eval-cases/export")
  if (!response.ok) throw new Error("导出失败")
  return (await response.json()) as string
}