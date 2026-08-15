/** 共享类型。 */

/** NDJSON 事件（所有流式端点统一协议）。 */
export type StreamEvent =
  | { type: "stage"; stage: "match" | "resume" | "questions" | "consult" | "synthesis" | "knowledge" }
  | { type: "chunk"; text: string; agent?: string }
  | { type: "dispatch"; round: number; agents: string[]; tasks?: Record<string, string> }
  | { type: "agent_start"; agent: string; round?: number }
  | { type: "agent_end"; agent: string; round?: number }
  | {
      type: "done"; content: string; opinions?: Record<string, string>; calls?: ConsultCall[];
      sources?: KnowledgeSource[]; score?: number; feedback?: string;
      /** §9 稳定 ID：thread_id/turn_id/message_id/run_id/model/prompt_version/agent_version/status */
      thread_id?: string; turn_id?: string; message_id?: string; run_id?: string;
      model?: string; prompt_version?: string; agent_version?: string; status?: string;
      legacy_thread_id?: string;
    }
  | { type: "error"; message: string }
  | { type: "input_request"; message: string; fields: ConsultInputField[] }

export type StreamStatus = "idle" | "streaming" | "done" | "error"

/** 聊天消息。 */
export interface ChatMessage {
  /** UI key（turn 分组/React key/anchor 用；非后端稳定 message_id）。 */
  id: string
  role: "user" | "assistant"
  content: string
  agent?: string
  streaming?: boolean
  /** 后端稳定 ID（§2.2 / §9）：message_id / turn_id / run_id。 */
  messageId?: string
  turnId?: string
  runId?: string
}

/** 单条回答反馈（绑定 assistant message id）。 */
export interface MessageFeedback {
  messageId: string
  rating: "positive" | "negative"
  reason?:
    | "incorrect"
    | "not_helpful"
    | "did_not_answer"
    | "too_verbose"
    | "hard_to_understand"
    | "other"
  comment?: string
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
  category?: string
  /** 该来源的图片被顾问实际读取用于作答（替代低文本相关度展示）。 */
  used_image?: boolean
}

/** 会诊总调度官一次顾问调用记录。 */
export interface ConsultCall {
  round: number
  agent: string
  task: string
  content: string
}

/** 会诊"资料填写框"字段（总调度官判断信息不足时下发给前端）。 */
export interface ConsultInputField {
  id: string
  label: string
  placeholder?: string
  required?: boolean
}

/** 会诊 input_request 事件载荷：引导语 + 需要用户填写的字段。 */
export interface ConsultInputRequest {
  message: string
  fields: ConsultInputField[]
}

/** 前端兜底字段定义：后端未下发时按 id 补齐展示文案。 */
export const CONSULT_INPUT_FIELDS: ConsultInputField[] = [
  { id: "current_position", label: "当前职位 / 行业", placeholder: "例如：后端开发 / 互联网", required: true },
  { id: "experience_years", label: "工作年限", placeholder: "例如：3 年，中级", required: true },
  { id: "skills", label: "核心技能", placeholder: "例如：Python、RAG、大模型微调", required: true },
  { id: "target_direction", label: "目标方向", placeholder: "例如：大模型工程师、Agent 工程师", required: true },
  { id: "city", label: "期望城市", placeholder: "例如：上海、杭州", required: false },
  { id: "salary", label: "期望薪资", placeholder: "例如：目前 20k，期望 30-35k", required: false },
  { id: "target_companies", label: "目标公司", placeholder: "例如：字节、阿里（可填多个）", required: false },
]

/** 知识库分类（与后端 careercrew_core/rag/categories.py 对齐）。 */
export const KB_CATEGORIES = [
  { id: "", label: "全部" },
  { id: "resume", label: "简历" },
  { id: "knowledge", label: "学习资料" },
  { id: "interview", label: "面试题" },
  { id: "job", label: "岗位/JD" },
] as const

export const KB_CATEGORY_LABELS: Record<string, string> = {
  resume: "简历",
  knowledge: "学习资料",
  interview: "面试题",
  job: "岗位/JD",
}

export const KB_SCOPE = [
  { id: "all", label: "全部" },
  { id: "public", label: "公共库" },
  { id: "private", label: "个人库" },
] as const

export const KB_SCOPE_LABELS: Record<string, string> = {
  all: "全部",
  public: "公共库",
  private: "个人库",
}


/** 会诊 agent 选项。 */
export const CONSULT_AGENTS = [
  { id: "salary_negotiator", label: "薪资谈判师", color: "#7C3AED" },
  { id: "career_planner", label: "职业规划师", color: "#2563EB" },
  { id: "job_matcher", label: "职位匹配官", color: "#0D9488" },
  { id: "resume_advisor", label: "简历顾问", color: "#D97706" },
  { id: "interviewer", label: "面试官", color: "#BE185D" },
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

/** 会诊总调度官身份色系（页面顶部逻辑角色）。 */
export const ORCHESTRATOR_META = { label: "总调度官", color: "#0F172A" }
