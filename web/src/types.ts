/** 共享类型。 */

/** NDJSON 事件（所有流式端点统一协议）。 */
export type StreamEvent =
  | { type: "stage"; stage: "match" | "resume" | "questions" | "consult" | "synthesis" }
  | { type: "chunk"; text: string; agent?: string }
  | { type: "agent_start"; agent: string }
  | { type: "agent_end"; agent: string }
  | { type: "done"; content: string; opinions?: Record<string, string> }
  | { type: "error"; message: string }

export type StreamStatus = "idle" | "streaming" | "done" | "error"

/** 聊天消息。 */
export interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  agent?: string
  streaming?: boolean
}

/** 面试 QA。 */
export interface InterviewQA {
  question: string
  answer: string
  score?: number
  feedback?: string
}

/** LangSmith run 摘要（GET /api/runs）。 */
export interface RunSummary {
  run_id: string
  name: string
  run_type: string
  start_time: string | null
  end_time: string | null
  duration_ms: number | null
  status: string
  error: string | null
  metadata: Record<string, string>
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
  estimated_cost: number | null
}

/** 子 run 时间线步骤（GET /api/runs/{id}）。 */
export interface RunStep {
  run_id: string
  name: string
  run_type: string
  start_time: string | null
  end_time: string | null
  duration_ms: number | null
  status: string
  error: string | null
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
  inputs_preview?: string
  outputs_preview?: string
}

export interface RunDetail {
  run: RunSummary
  steps: RunStep[]
}

/** 会诊 agent 选项。 */
export const CONSULT_AGENTS = [
  { id: "salary_negotiator", label: "薪资谈判师", color: "#7C3AED" },
  { id: "career_planner", label: "职业规划师", color: "#2563EB" },
] as const

/** Agent 身份色系：消息标签 + 左边框 + 会诊卡片标识。 */
export const AGENT_META: Record<string, { label: string; color: string }> = {
  job_matcher: { label: "职位匹配官", color: "#0D9488" },
  resume_advisor: { label: "简历顾问", color: "#D97706" },
  interviewer: { label: "面试官", color: "#BE185D" },
  salary_negotiator: { label: "薪资谈判师", color: "#7C3AED" },
  career_planner: { label: "职业规划师", color: "#2563EB" },
}
