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
  updateLastAssistant: (content: string, ids?: Pick<ChatMessage, "messageId" | "turnId" | "runId">) => void
  removeLastEmptyAssistant: () => void
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

  updateLastAssistant: (content, ids) =>
    set((s) => {
      const msgs = [...s.messages]
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === "assistant") {
          msgs[i] = { ...msgs[i], content, streaming: false, ...ids }
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
