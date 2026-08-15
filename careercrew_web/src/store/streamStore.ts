import { create } from "zustand"
import type { ConsultCall, ConsultInputRequest, KnowledgeSource, StreamEvent, StreamStatus } from "@/types"
import { useThreadStore } from "@/store/threadStore"
import { useChatStore } from "@/store/chatStore"
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
  /** done 事件携带的稳定 ID（§9）：message_id / turn_id / run_id / thread_id。 */
  doneIds: {
    messageId?: string
    turnId?: string
    runId?: string
    threadId?: string
    legacyThreadId?: string
  } | null
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
  doneIds: null,
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
  resetAll: () => void
}

export const useStreamStore = create<StreamStoreState>((set) => ({
  sessions: {},

  start: async (threadId, endpoint, body) => {
    // 同一会话重新发送：只终止该会话自己的旧请求，不影响其他会话
    controllers.get(threadId)?.abort()
    useThreadStore.getState().clearCompletedUnread(threadId)
    set((s) => ({ sessions: { ...s.sessions, [threadId]: freshSession(threadId) } }))

    // 会话 key：legacy remap 后指向新 UUID（done 事件携带 thread_id），
    // 后续所有 patchS/thinkTimers/controllers 都用新 key，保证页面按新 id 定位到本流。
    let sessionKey = threadId

    const patchS = (
      partial: Partial<StreamSession> | ((cur: StreamSession) => Partial<StreamSession>)
    ) =>
      set((s) => {
        const cur = s.sessions[sessionKey] ?? { ...IDLE_SESSION, threadId: sessionKey }
        const p = typeof partial === "function" ? partial(cur) : partial
        return { sessions: { ...s.sessions, [sessionKey]: { ...cur, ...p } } }
      })

    // thinkTimers / controllers 始终 keyed 到 sessionKey（可变）：legacy remap 后
    // sessionKey 指向新 UUID，同一把 timer/controller 需要跟着搬到新 key，
    // 否则 remap 前 arm 的 thinking timer 会残留旧 id、stop(newId) 也无法 abort 在途 fetch。
    const armThinking = () => {
      const prev = thinkTimers.get(sessionKey)
      if (prev) clearTimeout(prev)
      thinkTimers.set(
        sessionKey,
        setTimeout(() => patchS({ thinking: true }), 2000)
      )
    }
    const disarmThinking = () => {
      const prev = thinkTimers.get(sessionKey)
      if (prev) {
        clearTimeout(prev)
        thinkTimers.delete(sessionKey)
      }
      patchS({ thinking: false })
    }

    armThinking()
    const controller = new AbortController()
    controllers.set(sessionKey, controller)
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
              // §9 稳定 ID：message_id/turn_id/run_id（done 事件）+ thread_id（UUID）+ legacy_thread_id
              if (evt.message_id || evt.turn_id || evt.run_id) {
                p.doneIds = {
                  messageId: evt.message_id,
                  turnId: evt.turn_id,
                  runId: evt.run_id,
                  threadId: evt.thread_id,
                  legacyThreadId: evt.legacy_thread_id,
                }
              }
              patchS(p)
              // done → chatStore：把稳定 ID 挂到该轮 assistant 消息（最后一条 assistant）。
              const chat = useChatStore.getState()
              const msgs = [...chat.messages]
              for (let i = msgs.length - 1; i >= 0; i--) {
                if (msgs[i].role === "assistant") {
                  msgs[i] = {
                    ...msgs[i],
                    ...(evt.message_id ? { messageId: evt.message_id } : {}),
                    ...(evt.turn_id ? { turnId: evt.turn_id } : {}),
                    ...(evt.run_id ? { runId: evt.run_id } : {}),
                  }
                  break
                }
              }
              useChatStore.setState({ messages: msgs })
              // legacy remap：done 返回 UUID thread_id 与本地 id 不同 → 更新 chatStore + threadStore，
              // 后续请求用新 UUID；同时把流式 session 重新挂到新 id（否则页面按新 id 查不到该流）。
              if (evt.thread_id && evt.thread_id !== threadId) {
                useChatStore.getState().setThreadId(evt.thread_id)
                useThreadStore.getState().remapLegacyThread(threadId, evt.thread_id)
                // re-key 在途 controller + thinking timer 到新 UUID：否则 stop(newId)
                // 查不到 controller、无法 abort 本请求，thinkTimers 也残留旧 id。
                const ctrl = controllers.get(sessionKey)
                if (ctrl) {
                  controllers.delete(sessionKey)
                  controllers.set(evt.thread_id, ctrl)
                }
                const prevTimer = thinkTimers.get(sessionKey)
                if (prevTimer) {
                  thinkTimers.delete(sessionKey)
                  thinkTimers.set(evt.thread_id, prevTimer)
                }
                sessionKey = evt.thread_id
                set((s) => {
                  const cur = s.sessions[threadId]
                  if (!cur) return {}
                  const sessions = { ...s.sessions }
                  delete sessions[threadId]
                  sessions[evt.thread_id!] = { ...cur, threadId: evt.thread_id! }
                  return { sessions }
                })
              }
              // 会话完成（可能发生在用户正看着别的会话时）：刷新侧边栏列表。
              // 注意顺序：此判断必须在 remap 之后读取 currentThreadByModule——remap 已把
              // 当前 module 的 currentThreadByModule 切到新 UUID，所以「正在看的会话」仍被
              // newThreadId（新 UUID）命中也算 active，不会误打未读圆点。
              const newThreadId = evt.thread_id ?? threadId
              const activeIds = Object.values(useThreadStore.getState().currentThreadByModule)
              if (!activeIds.includes(newThreadId)) {
                // 未在看的会话完成：打蓝色圆点，点击该会话后清除
                useThreadStore.getState().markCompletedUnread(newThreadId)
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
      // sessionKey（可能已被 remap 成新 UUID）才是 controller 当前所在 key
      controllers.delete(sessionKey)
    }
  },

  stop: (threadId) => {
    controllers.get(threadId)?.abort()
  },

  reset: (threadId) => {
    set((s) => ({ sessions: { ...s.sessions, [threadId]: { ...IDLE_SESSION, threadId } } }))
  },

  resetAll: () => {
    // 登出/切换用户：中止所有在途流并清空会话状态，防止跨用户数据残留
    controllers.forEach((c) => c.abort())
    controllers.clear()
    set({ sessions: {} })
  },
}))
