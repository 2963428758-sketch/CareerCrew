import { create } from "zustand"
import type { ChatMessage, ConsultCall, ConsultInputRequest, KnowledgeSource, StreamEvent, StreamStatus } from "@/types"
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
  start: (threadId: string, endpoint: string, body: Record<string, unknown>, opts?: { regenerate?: boolean }) => Promise<void>
  /** §19：重新生成最后一条完整 assistant 消息（POST /api/messages/{id}/regenerate）。 */
  regenerate: (threadId: string, messageId: string) => Promise<void>
  stop: (threadId: string) => void
  reset: (threadId: string) => void
  resetAll: () => void
}

export const useStreamStore = create<StreamStoreState>((set, get) => ({
  sessions: {},

  start: async (threadId, endpoint, body, opts) => {
    const isRegenerate = Boolean(opts?.regenerate)
    // 同一会话重新发送：只终止该会话自己的旧请求，不影响其他会话
    controllers.get(threadId)?.abort()
    useThreadStore.getState().clearCompletedUnread(threadId)
    set((s) => ({ sessions: { ...s.sessions, [threadId]: freshSession(threadId) } }))

    // 会话 key 默认保持请求使用的 legacy id；只有服务端没有返回对应 legacy 映射时，
    // 才把真正的旧客户端 key remap 到 canonical UUID。
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

      // chunk 高频到达（每 token 一次）：本地累积 + ~50ms 合并刷盘，避免每 chunk
      // 触发一次全 store set（整页重渲染）。非 chunk 事件与流结束前强制 flush，
      // 保证 stage/done/error 等状态不丢、最终文本完整。
      let flushTimer: ReturnType<typeof setTimeout> | null = null
      const flushNow = () => {
        if (flushTimer) {
          clearTimeout(flushTimer)
          flushTimer = null
        }
        patchS({ streamingText: textAccum, agentChunks: { ...agentAccum } })
      }
      const scheduleFlush = () => {
        if (flushTimer) return
        flushTimer = setTimeout(flushNow, 50)
      }

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

            if (evt.type === "stage") {
              flushNow()
              patchS({ stage: evt.stage })
            } else if (evt.type === "dispatch") {
              flushNow()
              patchS({ dispatch: { round: evt.round, agents: evt.agents } })
            } else if (evt.type === "chunk") {
              disarmThinking()
              armThinking()
              if (evt.agent) {
                agentAccum[evt.agent] = (agentAccum[evt.agent] ?? "") + evt.text
              } else {
                textAccum += evt.text
              }
              scheduleFlush()
            } else if (evt.type === "agent_start" || evt.type === "agent_end") {
              disarmThinking()
              armThinking()
            } else if (evt.type === "done") {
              flushNow()
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
                  const patched: ChatMessage = {
                    ...msgs[i],
                    ...(evt.message_id ? { messageId: evt.message_id } : {}),
                    ...(evt.turn_id ? { turnId: evt.turn_id } : {}),
                    ...(evt.run_id ? { runId: evt.run_id } : {}),
                    ...(evt.regenerated_from_message_id ? { regeneratedFromMessageId: evt.regenerated_from_message_id } : {}),
                    content: evt.content,
                    streaming: false,
                  }
                  if (isRegenerate) {
                    // §19：regenerate 不覆盖旧消息——把新版本作为独立 ChatMessage 追加，
                    // 与旧版本共享 turnId；groupTurns 按 turnId 把同 turn 的 assistant 归入 versions。
                    // 若最后一个 assistant 是本次流占位符（空内容、无 messageId），则原位替换为
                    // 新版本；否则追加新版本。旧消息对象从不 mutate。
                    const isPlaceholder = !msgs[i].content && !msgs[i].messageId
                    if (isPlaceholder) {
                      const patchedMsgs = [...msgs]
                      patchedMsgs[i] = patched
                      useChatStore.setState({ messages: patchedMsgs })
                    } else {
                      useChatStore.setState({ messages: [...msgs, patched] })
                    }
                  } else {
                    const patchedMsgs = [...msgs]
                    patchedMsgs[i] = patched
                    useChatStore.setState({ messages: patchedMsgs })
                  }
                  break
                }
              }
              // 只有 done 没有声明当前 legacy 映射时才 remap。正常 legacy 请求会同时收到
              // UUID thread_id + legacy_thread_id；若此时切换到 UUID，下一轮 memory 写入会
              // 把同一会话拆成第二条历史记录。
              if (
                evt.thread_id
                && evt.thread_id !== threadId
                && evt.legacy_thread_id !== threadId
              ) {
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
              const newThreadId = evt.legacy_thread_id === threadId
                ? threadId
                : (evt.thread_id ?? threadId)
              const activeIds = Object.values(useThreadStore.getState().currentThreadByModule)
              if (!activeIds.includes(newThreadId)) {
                // 未在看的会话完成：打蓝色圆点，点击该会话后清除
                useThreadStore.getState().markCompletedUnread(newThreadId)
              }
              useThreadStore.getState().bumpNonce()
            } else if (evt.type === "input_request") {
              flushNow()
              patchS({ pendingInput: { message: evt.message, fields: evt.fields } })
            } else if (evt.type === "error") {
              flushNow()
              patchS({ errorMsg: evt.message, status: "error" })
            }
          } catch {
            // 忽略解析失败的行
          }
        }
      }

      // 流自然结束：把尚未刷盘的尾部 chunk 落地（并清掉挂起的 timer，防止
      // 迟到的 flush 写进已被 reset 的新会话）。
      flushNow()
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

  regenerate: (threadId, messageId) =>
    get().start(threadId, `/messages/${encodeURIComponent(messageId)}/regenerate`, {}, { regenerate: true }),

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
