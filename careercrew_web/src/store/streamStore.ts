import { create } from "zustand"
import type { ConsultCall, ConsultInputRequest, KnowledgeSource, StreamEvent, StreamStatus } from "@/types"
import { useThreadStore } from "@/store/threadStore"
import { apiFetch } from "@/lib/auth"

/**
 * 每会话（thread_id）独立的流式会话 store（Codex 式并行对话）。
 *
 * 关键点：
 * - 每个 thread_id 一个 StreamSession，各自持有独立的 AbortController 与状态；
 * - 切换到其他会话/模块不会中断正在运行的流（旧会话继续在后台完整接收回答）；
 * - 同一会话重复发送时才会终止该会话自己的旧请求；
 * - 会话完成（done 事件）后 bump 侧边栏 nonce，让列表刷新。
 */
export interface StreamSession {
  threadId: string
  status: StreamStatus
  events: StreamEvent[]
  streamingText: string
  agentChunks: Record<string, string>
  stage: string
  doneContent: string
  doneSources: KnowledgeSource[]
  doneScore?: number
  doneFeedback?: string
  opinions: Record<string, string>
  dispatch: { round: number; agents: string[] } | null
  calls: ConsultCall[]
  errorMsg: string
  thinking: boolean
  /** 会诊信息不足时后端下发的资料填写请求（前端据此弹窗）。 */
  pendingInput: ConsultInputRequest | null
}

/** 无会话时的共享空态（只读，禁止 mutate）。 */
export const IDLE_SESSION: StreamSession = {
  threadId: "",
  status: "idle",
  events: [],
  streamingText: "",
  agentChunks: {},
  stage: "",
  doneContent: "",
  doneSources: [],
  doneScore: undefined,
  doneFeedback: undefined,
  opinions: {},
  dispatch: null,
  calls: [],
  errorMsg: "",
  thinking: false,
  pendingInput: null,
}

const freshSession = (threadId: string): StreamSession => ({
  ...IDLE_SESSION,
  threadId,
  status: "streaming",
})

const controllers = new Map<string, AbortController>()
const thinkTimers = new Map<string, ReturnType<typeof setTimeout>>()

interface StreamStoreState {
  sessions: Record<string, StreamSession>
  start: (threadId: string, endpoint: string, body: Record<string, unknown>) => Promise<void>
  stop: (threadId: string) => void
  reset: (threadId: string) => void
}

export const useStreamStore = create<StreamStoreState>((set) => ({
  sessions: {},

  start: async (threadId, endpoint, body) => {
    // 同一会话重新发送：只终止该会话自己的旧请求，不影响其他会话
    controllers.get(threadId)?.abort()
    useThreadStore.getState().clearCompletedUnread(threadId)
    set((s) => ({ sessions: { ...s.sessions, [threadId]: freshSession(threadId) } }))

    const patchS = (
      partial: Partial<StreamSession> | ((cur: StreamSession) => Partial<StreamSession>)
    ) =>
      set((s) => {
        const cur = s.sessions[threadId] ?? { ...IDLE_SESSION, threadId }
        const p = typeof partial === "function" ? partial(cur) : partial
        return { sessions: { ...s.sessions, [threadId]: { ...cur, ...p } } }
      })

    const armThinking = () => {
      const prev = thinkTimers.get(threadId)
      if (prev) clearTimeout(prev)
      thinkTimers.set(
        threadId,
        setTimeout(() => patchS({ thinking: true }), 2000)
      )
    }
    const disarmThinking = () => {
      const prev = thinkTimers.get(threadId)
      if (prev) {
        clearTimeout(prev)
        thinkTimers.delete(threadId)
      }
      patchS({ thinking: false })
    }

    armThinking()
    const controller = new AbortController()
    controllers.set(threadId, controller)
    patchS({ dispatch: null, calls: [] })

    try {
      const resp = await apiFetch(`/api${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      })

      if (!resp.ok) {
        const text = await resp.text().catch(() => "")
        throw new Error(`HTTP ${resp.status}: ${text}`)
      }

      const reader = resp.body?.getReader()
      if (!reader) throw new Error("无法获取响应流")

      const decoder = new TextDecoder()
      let buffer = ""
      let textAccum = ""
      const agentAccum: Record<string, string> = {}
      const eventsAccum: StreamEvent[] = []

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split("\n")
        buffer = lines.pop() ?? ""

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue
          try {
            const evt = JSON.parse(trimmed) as StreamEvent
            eventsAccum.push(evt)
            patchS({ events: [...eventsAccum] })

            if (evt.type === "stage") {
              patchS({ stage: evt.stage })
            } else if (evt.type === "dispatch") {
              patchS({ dispatch: { round: evt.round, agents: evt.agents } })
            } else if (evt.type === "chunk") {
              disarmThinking()
              armThinking()
              if (evt.agent) {
                agentAccum[evt.agent] = (agentAccum[evt.agent] ?? "") + evt.text
                patchS({ agentChunks: { ...agentAccum } })
              } else {
                textAccum += evt.text
                patchS({ streamingText: textAccum })
              }
            } else if (evt.type === "agent_start" || evt.type === "agent_end") {
              disarmThinking()
              armThinking()
            } else if (evt.type === "done") {
              const p: Partial<StreamSession> = {
                doneContent: evt.content,
                status: "done",
              }
              if (evt.opinions) p.opinions = evt.opinions
              if (evt.calls) p.calls = evt.calls
              if (evt.sources) p.doneSources = evt.sources
              if (evt.score !== undefined) p.doneScore = evt.score
              if (evt.feedback !== undefined) p.doneFeedback = evt.feedback
              patchS(p)
              // 会话完成（可能发生在用户正看着别的会话时）：刷新侧边栏列表
              const activeIds = Object.values(useThreadStore.getState().currentThreadByModule)
              if (!activeIds.includes(threadId)) {
                // 未在看的会话完成：打蓝色圆点，点击该会话后清除
                useThreadStore.getState().markCompletedUnread(threadId)
              }
              useThreadStore.getState().bumpNonce()
            } else if (evt.type === "input_request") {
              patchS({ pendingInput: { message: evt.message, fields: evt.fields } })
            } else if (evt.type === "error") {
              patchS({ errorMsg: evt.message, status: "error" })
            }
          } catch {
            // 忽略解析失败的行
          }
        }
      }

      patchS((s) => ({
        status: s.status === "streaming" ? "done" : s.status,
      }))
    } catch (e) {
      if ((e as Error).name === "AbortError") {
        patchS({ status: "idle" })
        return
      }
      patchS({ errorMsg: (e as Error).message, status: "error" })
    } finally {
      disarmThinking()
      controllers.delete(threadId)
    }
  },

  stop: (threadId) => {
    controllers.get(threadId)?.abort()
  },

  reset: (threadId) => {
    set((s) => ({ sessions: { ...s.sessions, [threadId]: { ...IDLE_SESSION, threadId } } }))
  },
}))
