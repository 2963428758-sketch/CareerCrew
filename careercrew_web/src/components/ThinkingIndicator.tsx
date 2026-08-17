import { Loader2 } from "lucide-react"

/** 初始化阶段：模型/向量库加载中（轻微转圈 + 静默文字）。 */
export function InitIndicator({ text = "正在初始化模型与向量库" }: { text?: string }) {
  return (
    <div className="flex items-center gap-2 text-[13px] text-ink-soft">
      <Loader2 className="h-3.5 w-3.5 animate-spin text-ink-faint" />
      <span>{text}</span>
    </div>
  )
}

/** 思考中：agent 正在调用工具（搜索/检索），无新 chunk —— 柔和透明度脉冲。 */
export function ThinkingPulse() {
  return (
    <div className="mt-2 flex items-center gap-1.5 text-[11.5px] text-ink-faint">
      <span className="working-pulse h-1.5 w-1.5 rounded-full bg-current" />
      <span>正在搜索和检索…</span>
    </div>
  )
}
