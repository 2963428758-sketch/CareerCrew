/** 共享类型。 */

/** NDJSON 事件（所有流式端点统一协议）。 */
export type StreamEvent =
  | { type: "stage"; stage: "match" | "resume" | "questions" | "consult" | "synthesis" | "knowledge" }
  | { type: "chunk"; text: string; agent?: string }
  | { type: "agent_start"; agent: string }
  | { type: "agent_end"; agent: string }
  | { type: "done"; content: string; opinions?: Record<string, string>; sources?: KnowledgeSource[] }
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

/** 知识库问答的来源片段（done 事件携带，前端可点击查看原文）。 */
export interface KnowledgeSource {
  doc: string
  source: string
  score: number
  text: string
  image_path?: string
  page?: number | null
}


/** 会诊 agent 选项。 */
export const CONSULT_AGENTS = [
  { id: "job_matcher", label: "职位匹配官", color: "#0D9488" },
  { id: "resume_advisor", label: "简历顾问", color: "#D97706" },
  { id: "interviewer", label: "面试官", color: "#BE185D" },
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
  knowledge_advisor: { label: "知识库顾问", color: "#16A34A" },
}
