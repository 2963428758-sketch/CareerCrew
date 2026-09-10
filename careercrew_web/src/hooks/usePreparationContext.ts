import { useEffect, useState } from "react"

import { getPrepSession, type PreparationSession } from "@/lib/preparation"

/** 各模块准备会话的线程前缀（与后端 PreparationStore 约定一致）。 */
const PREFIX: Record<"resume" | "interview", string> = {
  resume: "r-prep-",
  interview: "i-prep-",
}

/**
 * 按当前线程加载岗位准备上下文（仅 r-prep- / i-prep- 前缀线程）。
 * 线程或账号变化后，迟到响应一律丢弃；非准备线程恒为 null。
 */
export function usePreparationContext(module: "resume" | "interview", threadId: string): {
  prepSession: PreparationSession | null
  prepLoading: boolean
} {
  const [prepSession, setPrepSession] = useState<PreparationSession | null>(null)
  const [prepLoading, setPrepLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    setPrepSession(null)
    setPrepLoading(false)
    if (!threadId || !threadId.startsWith(PREFIX[module])) return
    setPrepLoading(true)
    getPrepSession(threadId)
      .then((s) => {
        if (!cancelled) setPrepSession(s)
      })
      .catch(() => {
        if (!cancelled) setPrepSession(null)
      })
      .finally(() => {
        if (!cancelled) setPrepLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [module, threadId])

  return { prepSession, prepLoading }
}
