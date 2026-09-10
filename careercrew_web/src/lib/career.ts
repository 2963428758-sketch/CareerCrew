import { apiFetch } from "@/lib/auth"
import { apiErrorText } from "@/lib/errors"

/** 求职跟进域（/api/career）客户端。 */

export const BOARD_STAGES = ["待准备", "已投递", "沟通中", "面试中", "收到Offer", "已结束"] as const
export type BoardStage = (typeof BOARD_STAGES)[number]

export interface BoardRow {
  opportunity_id: string
  company: string
  title: string
  stage: string
  next_action: string
  next_action_date: string
  note: string
  stage_updated_at: string
  updated_at: string
}

export interface StageChange {
  id: string
  from_stage: string
  to_stage: string
  note: string
  created_at: string
}

export interface Material {
  id: string
  name: string
  background: string
  role: string
  actions: string
  results: string
  tags: string[]
  confirmed: boolean
  created_at: string
  updated_at: string
}

export interface ActionItem {
  id: string
  title: string
  note: string
  due_date: string
  opportunity_id: string
  done: boolean
  postponed_count: number
  dismissed: boolean
  created_at: string
  updated_at: string
}

export interface HRFollowup {
  id: string
  company: string
  title: string
  channel: string
  content: string
  received_at: string
  opportunity_id: string
  todo_note: string
  reply_draft: string
  draft_confirmed: boolean
  resolved: boolean
  created_at: string
  updated_at: string
}

export interface Offer {
  id: string
  company: string
  title: string
  base_salary: string
  bonus: string
  equity: string
  location: string
  work_mode: string
  growth: string
  notes: string
  opportunity_id: string
  created_at: string
  updated_at: string
}

export interface RealInterviewRecord {
  id: string
  company: string
  title: string
  interview_date: string
  stage: string
  questions: Array<{ question: string; answer: string; reflection: string }>
  overall_reflection: string
  weak_points: string[]
  created_at: string
}

export interface InterviewReport {
  id: string
  thread_id: string
  report: {
    total_questions: number
    scored_questions: number
    avg_score: number | null
    summary?: string
    strengths: Array<Record<string, unknown> | string>
    weaknesses: Array<Record<string, unknown> | string>
    practice_suggestions?: string[]
    by_question: Array<{ question: string; answer: string; score: number | null; feedback: string }>
    source: string
  }
  created_at: string
}

export interface JobStats {
  by_stage: Record<string, number>
  by_source: Record<string, { total: number; by_stage: Record<string, number> }>
  by_version: Record<string, { total: number; by_stage: Record<string, number> }>
  applied: number
  replies: number
  interviewed: number
  offers: number
  reply_rate: { numerator: number; denominator: number; rate: number | null }
  interview_rate: { numerator: number; denominator: number; rate: number | null }
  offer_rate: { numerator: number; denominator: number; rate: number | null }
  tasks: { open: number; done: number }
}

export interface CareerProfile {
  owner_id?: string
  stage: string
  city: string
  goal: string
  onboarding_done: boolean
  updated_at?: string
}

export interface SearchItem { id: string; kind: string; title: string; summary: string }
export interface SearchResult {
  items: SearchItem[]
  next_cursor: string | null
  opportunities: Array<{ id: string; company: string; title: string; jd: string; stage: string }>
  materials: Array<{ id: string; name: string; background: string }>
  real_interviews: Array<{ id: string; company: string; title: string; overall_reflection: string }>
  offers: Array<{ id: string; company: string; title: string; notes: string }>
  tasks: Array<{ id: string; title: string; note: string }>
}

async function readData<T>(resp: Response): Promise<T> {
  if (!resp.ok) throw new Error(await apiErrorText(resp))
  return resp.json() as Promise<T>
}

function req(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }
}

// ── 看板 ──

export const listBoard = async (): Promise<BoardRow[]> => {
  const rows = await readData<BoardRow[]>(await apiFetch("/api/career/board"))
  return Array.isArray(rows) ? rows : []
}

export const updateBoard = async (
  opportunityId: string,
  payload: { stage: string; next_action?: string; next_action_date?: string; note?: string },
): Promise<BoardRow> => readData(await apiFetch(
  `/api/career/board/${encodeURIComponent(opportunityId)}`, req("PUT", payload)))

export const listStageChanges = async (opportunityId: string): Promise<StageChange[]> => {
  const rows = await readData<StageChange[]>(await apiFetch(
    `/api/career/board/${encodeURIComponent(opportunityId)}/log`))
  return Array.isArray(rows) ? rows : []
}

/** 岗位档案时间线事件（收藏/版本/会话/阶段/任务/HR/Offer/复盘 聚合）。 */
export interface TimelineEvent {
  kind: "created" | "resume_version" | "session" | "stage" | "task" | "followup" | "offer" | "review"
  at: string
  title: string
  detail: string
}

export const getOpportunityTimeline = async (
  opportunityId: string,
): Promise<{ opportunity_id: string; events: TimelineEvent[] }> => readData(await apiFetch(
  `/api/career/opportunities/${encodeURIComponent(opportunityId)}/timeline`))

// ── 素材库 ──

export const listMaterials = async (): Promise<Material[]> => {
  const rows = await readData<Material[]>(await apiFetch("/api/career/materials"))
  return Array.isArray(rows) ? rows : []
}

export const createMaterial = async (
  payload: Partial<Material>,
): Promise<Material> => readData(await apiFetch("/api/career/materials", req("POST", payload)))

export const updateMaterial = async (
  id: string,
  payload: Partial<Material>,
): Promise<Material> => readData(await apiFetch(
  `/api/career/materials/${encodeURIComponent(id)}`, req("PUT", payload)))

export const deleteMaterial = async (id: string): Promise<void> => {
  await readData(await apiFetch(`/api/career/materials/${encodeURIComponent(id)}`, req("DELETE")))
}

// ── 行动任务 ──

export const listTasks = async (): Promise<ActionItem[]> => {
  const rows = await readData<ActionItem[]>(await apiFetch("/api/career/tasks"))
  return Array.isArray(rows) ? rows : []
}

export const createTask = async (payload: {
  title: string
  note?: string
  due_date?: string
  opportunity_id?: string
}): Promise<ActionItem> => readData(await apiFetch("/api/career/tasks", req("POST", payload)))

export const patchTask = async (
  id: string,
  payload: { done?: boolean; postponed_due_date?: string; dismissed?: boolean },
): Promise<ActionItem> => readData(await apiFetch(
  `/api/career/tasks/${encodeURIComponent(id)}`, req("PATCH", payload)))

export const deleteTask = async (id: string): Promise<void> => {
  await readData(await apiFetch(`/api/career/tasks/${encodeURIComponent(id)}`, req("DELETE")))
}

// ── HR 跟进 ──

export const listFollowups = async (): Promise<HRFollowup[]> => {
  const rows = await readData<HRFollowup[]>(await apiFetch("/api/career/followups"))
  return Array.isArray(rows) ? rows : []
}

export const createFollowup = async (payload: {
  company: string
  title?: string
  channel?: string
  content: string
  received_at?: string
  opportunity_id?: string
  todo_note?: string
}): Promise<HRFollowup> => readData(await apiFetch("/api/career/followups", req("POST", payload)))

export const setReplyDraft = async (
  id: string,
  payload: { reply_draft: string; confirmed: boolean },
): Promise<HRFollowup> => readData(await apiFetch(
  `/api/career/followups/${encodeURIComponent(id)}/reply-draft`, req("PUT", payload)))

export const resolveFollowup = async (id: string): Promise<HRFollowup> => readData(
  await apiFetch(`/api/career/followups/${encodeURIComponent(id)}/resolve`, req("POST")))

export const deleteFollowup = async (id: string): Promise<void> => {
  await readData(await apiFetch(`/api/career/followups/${encodeURIComponent(id)}`, req("DELETE")))
}

// ── Offer 对比 ──

export const listOffers = async (): Promise<Offer[]> => {
  const rows = await readData<Offer[]>(await apiFetch("/api/career/offers"))
  return Array.isArray(rows) ? rows : []
}

export const createOffer = async (payload: Partial<Offer>): Promise<Offer> => readData(
  await apiFetch("/api/career/offers", req("POST", payload)))

export const updateOffer = async (id: string, payload: Partial<Offer>): Promise<Offer> => readData(
  await apiFetch(`/api/career/offers/${encodeURIComponent(id)}`, req("PUT", payload)))

export const deleteOffer = async (id: string): Promise<void> => {
  await readData(await apiFetch(`/api/career/offers/${encodeURIComponent(id)}`, req("DELETE")))
}

// ── 真实面试复盘 ──

export const listRealInterviews = async (): Promise<RealInterviewRecord[]> => {
  const rows = await readData<RealInterviewRecord[]>(await apiFetch("/api/career/real-interviews"))
  return Array.isArray(rows) ? rows : []
}

export const createRealInterview = async (payload: {
  company: string
  title?: string
  interview_date?: string
  stage?: string
  questions?: Array<{ question: string; answer?: string; reflection?: string }>
  overall_reflection?: string
}): Promise<RealInterviewRecord> => readData(await apiFetch(
  "/api/career/real-interviews", req("POST", payload)))

export const deleteRealInterview = async (id: string): Promise<void> => {
  await readData(await apiFetch(`/api/career/real-interviews/${encodeURIComponent(id)}`, req("DELETE")))
}

// ── 模拟面试复盘报告 ──

export const createInterviewReview = async (threadId: string): Promise<InterviewReport> => readData(
  await apiFetch("/api/career/interview-review", req("POST", { thread_id: threadId })))

export const listInterviewReports = async (threadId?: string): Promise<InterviewReport[]> => {
  const qs = threadId ? `?thread_id=${encodeURIComponent(threadId)}` : ""
  const rows = await readData<InterviewReport[]>(await apiFetch(`/api/career/interview-reports${qs}`))
  return Array.isArray(rows) ? rows : []
}

// ── 可解释匹配 ──

export interface GapAnalysis {
  id: string
  opportunity_id: string
  version_id: string
  result: {
    requirements: Array<{ requirement: string; status: string; evidence?: string; note?: string }>
    source: string
  }
  created_at: string
}

export const createGapAnalysis = async (
  opportunityId: string,
  resumeVersionId: string,
): Promise<GapAnalysis> => readData(await apiFetch(
  `/api/career/opportunities/${encodeURIComponent(opportunityId)}/gap-analysis`,
  req("POST", { resume_version_id: resumeVersionId })))

export const listGapAnalyses = async (opportunityId: string): Promise<GapAnalysis[]> => {
  const rows = await readData<GapAnalysis[]>(await apiFetch(
    `/api/career/opportunities/${encodeURIComponent(opportunityId)}/gap-analysis`))
  return Array.isArray(rows) ? rows : []
}

// ── 统计 / 搜索 / 画像 / 隐私 ──

export const getStats = async (): Promise<JobStats> => readData(await apiFetch("/api/career/stats"))

export interface GenerationMetrics {
  total: number
  success_count: number
  fallback_count: number
  fallback_rate: number
  p95_latency_ms: number | null
  by_source: Record<string, number>
}

export interface ProductFunnel {
  counts: Record<string, number>
  note: string
}

export const getGenerationMetrics = async (): Promise<GenerationMetrics> =>
  readData(await apiFetch('/api/career/generation-metrics'))

export const getProductFunnel = async (): Promise<ProductFunnel> =>
  readData(await apiFetch('/api/career/events/funnel'))

export const globalSearch = async (q: string, cursor?: string): Promise<SearchResult> => readData(
  await apiFetch(`/api/career/search?q=${encodeURIComponent(q)}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`))

export const getProfile = async (): Promise<CareerProfile | null> => {
  const resp = await apiFetch("/api/career/profile")
  if (resp.status === 404) return null
  return readData(resp)
}

export const saveProfile = async (payload: CareerProfile): Promise<CareerProfile> => readData(
  await apiFetch("/api/career/profile", req("PUT", payload)))

export const exportPrivacyData = async (): Promise<Record<string, unknown>> => readData(
  await apiFetch("/api/career/privacy/export"))

export const purgePrivacyData = async (): Promise<{ ok: boolean; deleted: Record<string, number> }> =>
  readData(await apiFetch("/api/career/privacy/purge", req("POST")))

// ── 提醒中心 / ICS ──

export interface ReminderItem {
  kind: "task_overdue" | "task_due" | "action_overdue" | "action_due" | "followup"
  date: string
  title: string
  ref_id: string
}

export const listReminders = async (): Promise<{ items: ReminderItem[]; today: string }> => readData(
  await apiFetch("/api/career/reminders"))

export const downloadRemindersIcs = async (): Promise<Blob> => {
  const resp = await apiFetch("/api/career/reminders/ics")
  if (!resp.ok) throw new Error(await apiErrorText(resp))
  return resp.blob()
}

// ── ATS 体检（规则） ──

export interface AtsResult {
  checks: Array<{ item: string; status: "pass" | "warn"; note: string }>
  jd_coverage: { requirements: number; covered: number } | null
  source: string
}

export const runAtsCheck = async (opportunityId: string, resumeVersionId: string): Promise<AtsResult> => readData(
  await apiFetch(`/api/career/opportunities/${encodeURIComponent(opportunityId)}/ats-check`,
    req("POST", { resume_version_id: resumeVersionId })))

// ── 投递材料包 ──

export interface ApplicationKit {
  source: "llm" | "template"
  sections: {
    cover_letter: string
    self_intro: string
    greeting: string
    followup: string
    thank_you: string
  }
}

export const createApplicationKit = async (
  opportunityId: string,
  resumeVersionId: string,
): Promise<ApplicationKit> => readData(await apiFetch(
  `/api/career/opportunities/${encodeURIComponent(opportunityId)}/application-kit`,
  req("POST", { resume_version_id: resumeVersionId })))

// ── 联系人与内推 ──

export interface Contact {
  id: string
  contact_name: string
  company: string
  role: string
  channel: string
  contact_value: string
  opportunity_id: string
  notes: string
  next_contact_date: string
  created_at: string
  updated_at: string
}

export const listContacts = async (): Promise<Contact[]> => {
  const rows = await readData<Contact[]>(await apiFetch("/api/career/contacts"))
  return Array.isArray(rows) ? rows : []
}

export const createContact = async (payload: Partial<Contact>): Promise<Contact> => readData(
  await apiFetch("/api/career/contacts", req("POST", payload)))

export const updateContact = async (id: string, payload: Partial<Contact>): Promise<Contact> => readData(
  await apiFetch(`/api/career/contacts/${encodeURIComponent(id)}`, req("PUT", payload)))

export const deleteContact = async (id: string): Promise<void> => {
  await readData(await apiFetch(`/api/career/contacts/${encodeURIComponent(id)}`, req("DELETE")))
}

// ── 导师只读分享 ──

export interface ShareInfo {
  id: string
  token?: string
  kind: "opportunity" | "resume_version"
  ref_id: string
  mask_pii: boolean
  expires_at: string
  revoked_at: string | null
  created_at?: string
}

export const createShare = async (payload: {
  kind: "opportunity" | "resume_version"
  ref_id: string
  expires_days?: number
  mask_pii?: boolean
}): Promise<ShareInfo> => readData(await apiFetch("/api/career/shares", req("POST", payload)))

export const listShares = async (): Promise<ShareInfo[]> => {
  const rows = await readData<ShareInfo[]>(await apiFetch("/api/career/shares"))
  return Array.isArray(rows) ? rows : []
}

export const revokeShare = async (token: string): Promise<void> => {
  await readData(await apiFetch(`/api/career/shares/${encodeURIComponent(token)}`, req("DELETE")))
}

// ── 面试情报包 ──

export interface IntelBrief {
  source: string
  company_research: string
  likely_questions: string[]
  confirm_questions: string[]
  evidence: string[]
  disclaimer: string
}

export const createIntelBrief = async (
  opportunityId: string,
  resumeVersionId: string,
): Promise<IntelBrief> => readData(await apiFetch(
  `/api/career/opportunities/${encodeURIComponent(opportunityId)}/intel-brief`,
  req("POST", { resume_version_id: resumeVersionId })))
