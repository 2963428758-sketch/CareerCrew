import { Loader2 } from "lucide-react"

/** 初始化阶段：模型/向量库加载中 */
export function InitIndicator({ text = "正在初始化模型与向量库" }: { text?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
      <span>{text}</span>
      <span className="text-xs text-muted-foreground/60">首次约 10-30 秒</span>
    </div>
  )
}

/** 思考中：agent 正在调用工具（搜索/检索），无新 chunk */
export function ThinkingPulse() {
  return (
    <div className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className="flex gap-0.5">
        <span className="h-1 w-1 animate-bounce rounded-full bg-primary [animation-delay:-0.3s]" />
        <span className="h-1 w-1 animate-bounce rounded-full bg-primary [animation-delay:-0.15s]" />
        <span className="h-1 w-1 animate-bounce rounded-full bg-primary" />
      </span>
      <span>正在搜索和检索…</span>
    </div>
  )
}
