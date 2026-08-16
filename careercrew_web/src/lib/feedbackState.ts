import { useEffect, useState } from "react"
import { getThreadFeedback, type PersistedFeedback } from "@/lib/feedback"

type ThreadFeedbackState = Record<string, PersistedFeedback>

const feedbackByThread = new Map<string, ThreadFeedbackState>()
const inFlight = new Map<string, Promise<void>>()
const listeners = new Set<() => void>()

const notify = () => listeners.forEach((listener) => listener())

/** 线程反馈的 API-backed cache；同一轮 history 恢复共用一次 GET。 */
export function hydrateThreadFeedback(threadId: string): Promise<void> {
  const running = inFlight.get(threadId)
  if (running) return running
  const request = getThreadFeedback(threadId)
    .then((rows) => {
      feedbackByThread.set(threadId, Object.fromEntries(rows.map((row) => [row.messageId, row])))
      notify()
    })
    .finally(() => { inFlight.delete(threadId) })
  inFlight.set(threadId, request)
  return request
}

export function setPersistedFeedback(threadId: string, feedback: PersistedFeedback): void {
  feedbackByThread.set(threadId, { ...(feedbackByThread.get(threadId) ?? {}), [feedback.messageId]: feedback })
  notify()
}

export function removePersistedFeedback(threadId: string, messageId: string): void {
  const current = feedbackByThread.get(threadId) ?? {}
  if (!(messageId in current)) return
  const { [messageId]: _removed, ...rest } = current
  feedbackByThread.set(threadId, rest)
  notify()
}

export function usePersistedFeedback(threadId: string, messageId: string): PersistedFeedback | null {
  const [feedback, setFeedback] = useState<PersistedFeedback | null>(() => feedbackByThread.get(threadId)?.[messageId] ?? null)
  useEffect(() => {
    const sync = () => setFeedback(feedbackByThread.get(threadId)?.[messageId] ?? null)
    sync()
    listeners.add(sync)
    return () => { listeners.delete(sync) }
  }, [threadId, messageId])
  return feedback
}

/** 测试隔离用；生产代码不应以本地 cache 作为持久化来源。 */
export function resetFeedbackStateForTest(): void {
  feedbackByThread.clear()
  inFlight.clear()
  notify()
}
