import { create } from "zustand"

export type ThreadModule = "chat" | "matcher" | "interview" | "knowledge" | "consult"

export interface ThreadItem {
  thread_id: string
  title: string
  module: string
  pinned: boolean
  created_at?: string
  updated_at?: string
  entries?: number
}

export interface ChatModuleMeta {
  key: ThreadModule
  label: string
  path: string
  prefix: string
}

export const CHAT_MODULES: ChatModuleMeta[] = [
  { key: "chat", label: "求职对话", path: "/", prefix: "t-" },
  { key: "matcher", label: "职位匹配", path: "/matcher", prefix: "m-" },
  { key: "interview", label: "面试练习", path: "/interview", prefix: "i-" },
  { key: "knowledge", label: "知识库问答", path: "/knowledge", prefix: "k-" },
  { key: "consult", label: "会诊", path: "/consult", prefix: "c-" },
]

/** 根据路由判断当前属于哪个对话模块；非对话页（数据看板/简历优化）返回 null。 */
export const moduleOfPath = (pathname: string): ThreadModule | null => {
  const hit = CHAT_MODULES.find((m) =>
    m.key === "chat" ? pathname === "/" : pathname === m.path || pathname.startsWith(`${m.path}/`)
  )
  return hit ? hit.key : null
}

const genThreadId = (module: ThreadModule): string => {
  const prefix = CHAT_MODULES.find((m) => m.key === module)?.prefix || "t-"
  return `${prefix}${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

/** 后端未返回 module 字段时，按 thread_id 前缀推断模块。 */
const inferModule = (tid: string): string => {
  const hit = CHAT_MODULES.find((m) => tid.startsWith(m.prefix))
  return hit ? hit.key : "unknown"
}

const initialCurrent: Record<string, string> = {}
for (const m of CHAT_MODULES) initialCurrent[m.key] = genThreadId(m.key)

interface ThreadState {
  activeModule: ThreadModule
  threadsByModule: Record<string, ThreadItem[]>
  currentThreadByModule: Record<string, string>
  loading: boolean
  error: string
  copiedThreadId: string | null
  /** 会话列表刷新信号（注册/删除/发送完成后 bump，侧边栏据此重新拉取） */
  nonce: number
  setActiveModule: (m: ThreadModule) => void
  fetchThreads: (m: ThreadModule) => Promise<void>
  selectThread: (m: ThreadModule, tid: string) => void
  registerThread: (m: ThreadModule) => Promise<string>
  touchThread: (m: ThreadModule, tid: string, title: string) => Promise<void>
  renameThread: (m: ThreadModule, tid: string, title: string) => Promise<void>
  togglePin: (m: ThreadModule, tid: string, pinned: boolean) => Promise<void>
  deleteThread: (m: ThreadModule, tid: string) => Promise<void>
  copyThreadId: (tid: string) => Promise<void>
  bumpNonce: () => void
}

const sortThreads = (list: ThreadItem[]): ThreadItem[] =>
  [...list].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
    const at = a.updated_at || a.created_at || ""
    const bt = b.updated_at || b.created_at || ""
    if (at && bt) return at < bt ? 1 : at > bt ? -1 : 0
    return 0
  })

export const useThreadStore = create<ThreadState>((set, get) => ({
  activeModule: "chat",
  threadsByModule: {},
  currentThreadByModule: initialCurrent,
  loading: false,
  error: "",
  copiedThreadId: null,
  nonce: 0,

  setActiveModule: (m) => set({ activeModule: m }),

  fetchThreads: async (m) => {
    set({ loading: true, error: "" })
    try {
      const resp = await fetch(`/api/threads?module=${m}`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data: unknown = await resp.json()
      const list: ThreadItem[] = (Array.isArray(data) ? data : []).map((t) => {
        const tid = String((t as Record<string, unknown>).thread_id || "")
        return {
          thread_id: tid,
          title: String((t as Record<string, unknown>).title || tid),
          module: String((t as Record<string, unknown>).module || inferModule(tid)),
          pinned: Boolean((t as Record<string, unknown>).pinned),
          created_at: String((t as Record<string, unknown>).created_at || ""),
          updated_at: String((t as Record<string, unknown>).updated_at || ""),
          entries: Number((t as Record<string, unknown>).entries || 0),
        }
      })
      const filtered = list.filter((t) => t.module === m)
      set((s) => ({ threadsByModule: { ...s.threadsByModule, [m]: sortThreads(filtered) } }))
    } catch (e) {
      set({ error: (e as Error).message })
    } finally {
      set({ loading: false })
    }
  },

  selectThread: (m, tid) =>
    set((s) => ({
      activeModule: m,
      currentThreadByModule: { ...s.currentThreadByModule, [m]: tid },
    })),

  registerThread: async (m) => {
    const tid = genThreadId(m)
    set((s) => ({
      activeModule: m,
      currentThreadByModule: { ...s.currentThreadByModule, [m]: tid },
      nonce: s.nonce + 1,
    }))
    try {
      await fetch("/api/threads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: tid, module: m, title: "" }),
      })
    } catch {
      // 后端契约未就绪时静默降级：客户端仍使用该 thread_id
    }
    return tid
  },

  touchThread: async (m, tid, title) => {
    const trimmed = title.trim().slice(0, 30)
    if (!trimmed) return
    set((s) => {
      const list = s.threadsByModule[m] || []
      const item = list.find((t) => t.thread_id === tid)
      if (!item || (item.title && item.title !== tid)) return s
      return {
        ...s,
        threadsByModule: {
          ...s.threadsByModule,
          [m]: list.map((t) => (t.thread_id === tid ? { ...t, title: trimmed } : t)),
        },
      }
    })
    try {
      await fetch(`/api/threads/${encodeURIComponent(tid)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: trimmed }),
      })
    } catch {
      // 后端未就绪时忽略，仅保留本地标题
    }
  },

  renameThread: async (m, tid, title) => {
    const trimmed = title.trim().slice(0, 50)
    if (!trimmed) return
    set((s) => ({
      threadsByModule: {
        ...s.threadsByModule,
        [m]: (s.threadsByModule[m] || []).map((t) =>
          t.thread_id === tid ? { ...t, title: trimmed } : t
        ),
      },
    }))
    try {
      await fetch(`/api/threads/${encodeURIComponent(tid)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: trimmed }),
      })
    } catch {
      // 后端未就绪：保留本地改名，下轮 fetch 可能被覆盖，属可接受降级
    }
  },

  togglePin: async (m, tid, pinned) => {
    set((s) => ({
      threadsByModule: {
        ...s.threadsByModule,
        [m]: sortThreads(
          (s.threadsByModule[m] || []).map((t) =>
            t.thread_id === tid ? { ...t, pinned } : t
          )
        ),
      },
    }))
    try {
      await fetch(`/api/threads/${encodeURIComponent(tid)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pinned }),
      })
    } catch {
      // 后端未就绪：仅本地生效
    }
  },

  deleteThread: async (m, tid) => {
    try {
      await fetch(`/api/threads/${encodeURIComponent(tid)}`, { method: "DELETE" })
    } catch {
      // 删除失败也先移除本地项，保持列表即时响应
    }
    const current = get().currentThreadByModule[m]
    if (current === tid) {
      await get().registerThread(m) // 当前会话被删 -> 自动进入新会话
    }
    set((s) => ({
      nonce: s.nonce + 1,
      threadsByModule: {
        ...s.threadsByModule,
        [m]: (s.threadsByModule[m] || []).filter((t) => t.thread_id !== tid),
      },
    }))
  },

  copyThreadId: async (tid) => {
    try {
      await navigator.clipboard.writeText(tid)
    } catch {
      window.prompt("会话 ID（可手动复制）", tid)
    }
    set({ copiedThreadId: tid })
    setTimeout(() => {
      if (get().copiedThreadId === tid) set({ copiedThreadId: null })
    }, 1500)
  },

  bumpNonce: () => set((s) => ({ nonce: s.nonce + 1 })),
}))
