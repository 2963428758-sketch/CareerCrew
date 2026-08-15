import { create } from "zustand"
import type { ChatMessage } from "@/types"

interface ChatState {
  messages: ChatMessage[]
  threadId: string
  selectedJd: string
  lastMatchResult: string
  selectedThreadId: string | null
  profileNonce: number
  threadNonce: number
  addMessage: (msg: ChatMessage) => void
  updateLastAssistant: (content: string) => void
  removeLastEmptyAssistant: () => void
  /** §19：把 regenerate 产生的新 assistant 版本追加到指定 turn 的版本列表（不覆盖旧消息）。 */
  appendAssistantVersion: (turnId: string, msg: ChatMessage) => void
  setThreadId: (id: string) => void
  setSelectedJd: (jd: string) => void
  setLastMatchResult: (content: string) => void
  setSelectedThreadId: (id: string | null) => void
  bumpProfileNonce: () => void
  bumpThreadNonce: () => void
  clear: () => void
  newConversation: () => void
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  threadId: `t-${Date.now()}`,
  selectedJd: "",
  lastMatchResult: "",
  selectedThreadId: null,
  profileNonce: 0,
  threadNonce: 0,

  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),

  updateLastAssistant: (content) =>
    set((s) => {
      const msgs = [...s.messages]
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === "assistant") {
          msgs[i] = { ...msgs[i], content, streaming: false }
          break
        }
      }
      return { messages: msgs }
    }),

  removeLastEmptyAssistant: () =>
    set((s) => {
      const msgs = [...s.messages]
      const last = msgs[msgs.length - 1]
      if (last && last.role === "assistant" && last.streaming && !last.content) {
        msgs.pop()
        return { messages: msgs }
      }
      return {}
    }),

  // §19：新版本追加在「该 turn 最后一个 assistant 版本」之后，保持版本顺序（旧 → 新）。
  // 定位：从后往前找 turnId 匹配的最后一条 assistant；若消息未带 turnId，
  // 退化为追加到末尾（流式占位场景）。旧消息永不 mutate（spread 新建）。
  appendAssistantVersion: (turnId, msg) =>
    set((s) => {
      const msgs = [...s.messages]
      let idx = -1
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === "assistant" && msgs[i].turnId === turnId) {
          idx = i
          break
        }
      }
      if (idx >= 0) {
        msgs.splice(idx + 1, 0, msg)
      } else {
        msgs.push(msg)
      }
      return { messages: msgs }
    }),

  setThreadId: (id) => set({ threadId: id }),
  setSelectedJd: (jd) => set({ selectedJd: jd }),
  setLastMatchResult: (content) => set({ lastMatchResult: content }),
  setSelectedThreadId: (id) => set({ selectedThreadId: id }),
  bumpProfileNonce: () => set((s) => ({ profileNonce: s.profileNonce + 1 })),
  bumpThreadNonce: () => set((s) => ({ threadNonce: s.threadNonce + 1 })),

  clear: () => set({ messages: [], selectedJd: "", lastMatchResult: "" }),

  newConversation: () => set({
    messages: [],
    selectedJd: "",
    lastMatchResult: "",
    threadId: `t-${Date.now()}`,
  }),
}))
