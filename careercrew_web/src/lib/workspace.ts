import { apiFetch } from "@/lib/auth"
import { apiErrorText } from "@/lib/errors"

export interface WorkspaceSearchItem {
  message_id: string
  thread_id: string
  turn_id: string
  role: string
  snippet: string
  thread_title?: string | null
  created_at?: string | null
  score?: number
}

export interface WorkspaceBookmark {
  id: string
  message_id: string
  snippet: string
  note: string
  tags: string[]
  updated_at?: string | null
}

export interface WorkspaceActionItem {
  id: string
  source_message_id: string
  source_snippet: string
  title: string
  note: string
  due_date?: string | null
  status: "open" | "done" | "dismissed"
  updated_at?: string | null
}

export interface WorkspaceBranch {
  id: string
  source_thread_id: string
  cutoff_message_id: string
  branch_thread_id: string
  title: string
  message_count: number
  created_at?: string | null
}

export interface ConsultationReport {
  id: string
  thread_id: string
  source_message_id: string
  source_answer: string
  opinions: Record<string, string>
  consensus: Array<{ point: string; supporters: string[] }>
  disagreements: Array<{ agents: string[]; summary: string }>
  alternatives: Array<{ agent: string; recommendation: string; basis: string }>
  risks: Array<{ agent: string; summary: string }>
  evidence: Array<{ agent: string; source_type: string; tool: string; status: string; summary: string }>
  status: "draft" | "confirmed"
  version: number
  generated_at?: string
  updated_at?: string
}

export interface ConsultationPlan {
  id: string
  report_id: string
  title: string
  steps: Array<{ title: string; note?: string; status?: string }>
  status: "draft" | "confirmed"
  version: number
}

export interface ResumeMaster {
  id: string
  title: string
  description: string
  created_at?: string
  updated_at?: string
}

export interface ResumeVersion {
  id: string
  master_id: string
  parent_version_id?: string | null
  label: string
  content: string
  kind: "master" | "derived"
  version_number: number
  content_sha256: string
  created_at?: string
}

export interface ResumeMaterial {
  id: string
  title: string
  context: string
  role: string
  actions: string
  results: string
  tags: string[]
}

export interface ResumeAnnotation {
  id: string
  version_id: string
  start_offset: number
  end_offset: number
  note: string
  status: string
}

export interface ResumeExportJob {
  id: string
  version_ids: string[]
  formats: string[]
  status: "queued" | "running" | "done" | "failed"
  error?: string | null
  expires_at?: string | null
}

export interface ToolStatus {
  id: string
  name: string
  kind: "internal" | "mcp" | string
  configured: boolean
  enabled: boolean
  requires_hitl: boolean
  visible_for_module: boolean
  health: "ready" | "restricted" | "disabled" | string
  health_detail: string
}

export interface ToolCall {
  id: string
  tool_id: string
  module?: string | null
  agent_id?: string | null
  status?: string | null
  duration_ms?: number | null
  requires_hitl: boolean
  hitl_status?: string | null
  failure_category?: string | null
  error_summary?: string | null
  created_at?: string | null
}

type JsonInit = { method: "POST" | "PUT" | "PATCH"; body: unknown }

const jsonInit = ({ method, body }: JsonInit): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
})

async function read<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await apiFetch(input, init)
  if (!response.ok) throw new Error(await apiErrorText(response))
  return await response.json() as T
}

export async function searchWorkspace(query: string, limit = 20) {
  const params = new URLSearchParams({ q: query, limit: String(limit) })
  return read<{ mode: string; query: string; total: number; items: WorkspaceSearchItem[] }>(
    `/api/workspace/search?${params.toString()}`,
  )
}

export const listBookmarks = () => read<WorkspaceBookmark[]>("/api/workspace/bookmarks")
export const saveBookmark = (messageId: string, note = "") => read<WorkspaceBookmark>(
  `/api/workspace/messages/${encodeURIComponent(messageId)}/bookmark`,
  jsonInit({ method: "PUT", body: { note, tags: [] } }),
)
export const deleteBookmark = (messageId: string) => read<{ ok: boolean }>(
  `/api/workspace/messages/${encodeURIComponent(messageId)}/bookmark`,
  { method: "DELETE" },
)

export const listActionItems = () => read<WorkspaceActionItem[]>("/api/workspace/action-items")
export const createActionItem = (messageId: string, title: string) => read<WorkspaceActionItem>(
  "/api/workspace/action-items",
  jsonInit({ method: "POST", body: { message_id: messageId, title, note: "" } }),
)
export const updateActionItem = (itemId: string, status: WorkspaceActionItem["status"]) => read<WorkspaceActionItem>(
  `/api/workspace/action-items/${encodeURIComponent(itemId)}`,
  jsonInit({ method: "PATCH", body: { status } }),
)

export const listBranches = () => read<WorkspaceBranch[]>("/api/workspace/branches")
export const createBranch = (sourceThreadId: string, cutoffMessageId: string) => read<WorkspaceBranch>(
  "/api/workspace/branches",
  jsonInit({ method: "POST", body: {
    source_thread_id: sourceThreadId,
    cutoff_message_id: cutoffMessageId,
    title: "",
  } }),
)

export const listConsultationReports = () => read<ConsultationReport[]>("/api/workspace/consult-reports")
export const createConsultationReport = (messageId: string) => read<ConsultationReport>(
  "/api/workspace/consult-reports",
  jsonInit({ method: "POST", body: { message_id: messageId } }),
)
export const updateConsultationReport = (reportId: string, status: ConsultationReport["status"], version: number) => read<ConsultationReport>(
  `/api/workspace/consult-reports/${encodeURIComponent(reportId)}`,
  jsonInit({ method: "PATCH", body: { status, version } }),
)
export const createConsultationPlan = (reportId: string, title: string, steps: ConsultationPlan["steps"]) => read<ConsultationPlan>(
  `/api/workspace/consult-reports/${encodeURIComponent(reportId)}/plans`,
  jsonInit({ method: "POST", body: { title, steps } }),
)
export const listConsultationPlans = (reportId: string) => read<ConsultationPlan[]>(
  `/api/workspace/consult-reports/${encodeURIComponent(reportId)}/plans`,
)
export const updateConsultationPlan = (planId: string, status: ConsultationPlan["status"], version: number) => read<ConsultationPlan>(
  "/api/workspace/consult-plans/" + encodeURIComponent(planId),
  jsonInit({ method: "PATCH", body: { status, version } }),
)

export const listResumeMasters = () => read<ResumeMaster[]>("/api/workspace/resumes/masters")
export const createResumeMaster = (title: string, content: string, description = "") => read<ResumeMaster>(
  "/api/workspace/resumes/masters",
  jsonInit({ method: "POST", body: { title, content, description } }),
)
export const listResumeVersions = (masterId: string) => read<ResumeVersion[]>(
  `/api/workspace/resumes/masters/${encodeURIComponent(masterId)}/versions`,
)
export const createResumeVersion = (masterId: string, label: string, content: string, parentVersionId?: string) => read<ResumeVersion>(
  `/api/workspace/resumes/masters/${encodeURIComponent(masterId)}/versions`,
  jsonInit({ method: "POST", body: { label, content, parent_version_id: parentVersionId ?? null, kind: "derived" } }),
)
export const diffResumeVersions = (left: string, right: string) => read<{
  left_label: string; right_label: string; changed: boolean; unified_diff: string
}>(`/api/workspace/resumes/diff?left_version_id=${encodeURIComponent(left)}&right_version_id=${encodeURIComponent(right)}`)
export const listResumeMaterials = () => read<ResumeMaterial[]>("/api/workspace/resumes/materials")
export const createResumeMaterial = (title: string, results: string) => read<ResumeMaterial>(
  "/api/workspace/resumes/materials",
  jsonInit({ method: "POST", body: { title, results, context: "", role: "", actions: "", tags: [] } }),
)
export const listResumeAnnotations = (versionId: string) => read<ResumeAnnotation[]>(
  `/api/workspace/resumes/versions/${encodeURIComponent(versionId)}/annotations`,
)
export const createResumeAnnotation = (versionId: string, startOffset: number, endOffset: number, note: string) => read<ResumeAnnotation>(
  `/api/workspace/resumes/versions/${encodeURIComponent(versionId)}/annotations`,
  jsonInit({ method: "POST", body: { start_offset: startOffset, end_offset: endOffset, note } }),
)
export const createResumeExport = (versionIds: string[]) => read<ResumeExportJob>(
  "/api/workspace/resumes/exports",
  jsonInit({ method: "POST", body: { version_ids: versionIds, formats: ["pdf", "docx"] } }),
)
export const listResumeExports = () => read<ResumeExportJob[]>("/api/workspace/resumes/exports")
export const downloadResumeExport = (jobId: string) => apiFetch(
  `/api/workspace/resumes/exports/${encodeURIComponent(jobId)}/download`,
)

export const listToolStatus = (module = "chat") => read<{ module: string; tools: ToolStatus[] }>(
  `/api/tools?module=${encodeURIComponent(module)}`,
)
export const listToolCalls = () => read<ToolCall[]>("/api/tools/calls")
export const setToolPolicy = (toolId: string, enabled: boolean) => read<ToolStatus>(
  `/api/tools/${encodeURIComponent(toolId)}`,
  jsonInit({ method: "PUT", body: { enabled, reason: "工作台策略调整" } }),
)
