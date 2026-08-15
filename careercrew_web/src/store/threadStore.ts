import { create } from "zustand"
import { apiFetch } from "@/lib/auth"

export type ThreadModule = "chat" | "matcher" | "interview" | "knowledge" | "consult" | "resume"

/** 会话检索范围（与后端 RetrievalScopeRequest 对齐；历史会话无该字段时为 null → "全部"）。 */
export type RetrievalScope =
  | { type: "all" }
  | { type: "public" }
  | { type: "private" }
  | { type: "category"; category_id: string }

export interface ThreadItem {
  thread_id: string
  title: string
  module: string
  pinned: boolean
  retrieval_scope?: RetrievalScope | null
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
  // 会话类模块与侧边栏导航同序
  { key: "chat", label: "求职规划", path: "/", prefix: "t-" },
  { key: "matcher", label: "职位匹配", path: "/matcher", prefix: "m-" },
  { key: "interview", label: "面试练习", path: "/interview", prefix: "i-" },
  { key: "resume", label: "简历优化", path: "/resume", prefix: "r-" },
  { key: "consult", label: "会诊", path: "/consult", prefix: "c-" },
  { key: "knowledge", label: "知识库问答", path: "/knowledge", prefix: "k-" },
]

/** 根据路由判断当前属于哪个对话模块；非对话页（数据看板）返回 null。 */
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
  /** 回答完成且尚未点击查看的会话（蓝色圆点，点击该会话后清除） */
  completedUnread: Record<string, boolean>
  /** 会话列表刷新信号（注册/删除/发送完成后 bump，侧边栏据此重新拉取） */
  nonce: number
  setActiveModule: (m: ThreadModule) => void
  fetchThreads: (m: ThreadModule) => Promise<void>
  selectThread: (m: ThreadModule, tid: string) => void
  registerThread: (m: ThreadModule) => Promise<string>
  touchThread: (m: ThreadModule, tid: string, title: string) => Promise<void>
  setThreadScope: (m: ThreadModule, tid: string, scope: RetrievalScope) => Promise<void>
  renameThread: (m: ThreadModule, tid: string, title: string) => Promise<void>
  togglePin: (m: ThreadModule, tid: string, pinned: boolean) => Promise<void>
  deleteThread: (m: ThreadModule, tid: string) => Promise<void>
  copyThreadId: (tid: string) => Promise<void>
  markCompletedUnread: (tid: string) => void
  clearCompletedUnread: (tid: string) => void
  bumpNonce: () => void
  resetAll: () => void
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
  completedUnread: {},
  nonce: 0,

  setActiveModule: (m) => set({ activeModule: m }),

  fetchThreads: async (m) => {
    set({ loading: true, error: "" })
    try {
      const resp = await apiFetch(`/api/threads?module=${m}`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data: unknown = await resp.json()
      const list: ThreadItem[] = (Array.isArray(data) ? data : []).map((t) => {
        const tid = String((t as Record<string, unknown>).thread_id || "")
        return {
          thread_id: tid,
          title: String((t as Record<string, unknown>).title || tid),
          module: String((t as Record<string, unknown>).module || inferModule(tid)),
          pinned: Boolean((t as Record<string, unknown>).pinned),
          retrieval_scope: ((t as Record<string, unknown>).retrieval_scope ?? null) as
            | RetrievalScope
            | null,
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
    set((s) => {
      const unread = { ...s.completedUnread }
      delete unread[tid] // 点击该会话后蓝色圆点消失
      return {
        activeModule: m,
        currentThreadByModule: { ...s.currentThreadByModule, [m]: tid },
        completedUnread: unread,
      }
    }),

  registerThread: async (m) => {
    const tid = genThreadId(m)
    set((s) => ({
      activeModule: m,
      currentThreadByModule: { ...s.currentThreadByModule, [m]: tid },
      nonce: s.nonce + 1,
    }))
    // 延迟注册：空会话不写后端，首条消息时 touchThread(PATCH upsert) 才真正创建线程，
    // 避免删除当前会话后列表冒出无标题的占位会话。
    return tid
  },

  touchThread: async (m, tid, title) => {
    const trimmed = title.trim().slice(0, 30)
    if (!trimmed) return
    set((s) => {
      const list = s.threadsByModule[m] || []
      const item = list.find((t) => t.thread_id === tid)
      // 新会话首条消息：本地立即插入该行（流式期间就能看到脉冲圆点），
      // 后端 PATCH 异步补齐，完成时 bumpNonce 重新拉取对齐。
      const nextList = item
        ? list.map((t) => (t.thread_id === tid ? { ...t, title: trimmed } : t))
        : [...list, { thread_id: tid, title: trimmed, module: m, pinned: false }]
      return {
        ...s,
        threadsByModule: {
          ...s.threadsByModule,
          [m]: sortThreads(nextList),
        },
      }
    })
    try {
      await apiFetch(`/api/threads/${encodeURIComponent(tid)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: trimmed, module: m }),
      })
    } catch {
      // 后端未就绪时忽略，仅保留本地标题
    }
  },

  setThreadScope: async (m, tid, scope) => {
    // 乐观更新本地列表：切换会话时立即恢复保存的范围
    set((s) => ({
      threadsByModule: {
        ...s.threadsByModule,
        [m]: (s.threadsByModule[m] || []).map((t) =>
          t.thread_id === tid ? { ...t, retrieval_scope: scope } : t
        ),
      },
    }))
    const body = JSON.stringify({ retrieval_scope: scope })
    try {
      const resp = await apiFetch(`/api/threads/${encodeURIComponent(tid)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body,
      })
      if (resp.status === 404) {
        // 尚未注册的会话（未发过消息）：先创建线程行再写范围
        await apiFetch("/api/threads", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ thread_id: tid, module: m, retrieval_scope: scope }),
        })
      }
    } catch {
      // 后端未就绪：保留本地范围，下轮 fetchThreads 会以服务端为准
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
      await apiFetch(`/api/threads/${encodeURIComponent(tid)}`, {
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
      await apiFetch(`/api/threads/${encodeURIComponent(tid)}`, {
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
      await apiFetch(`/api/threads/${encodeURIComponent(tid)}`, { method: "DELETE" })
    } catch {
      // 删除失败也先移除本地项，保持列表即时响应
    }
    const current = get().currentThreadByModule[m]
    if (current === tid) {
      await get().registerThread(m) // 当前会话被删 -> 自动进入新会话
    }
    set((s) => ({
      nonce: s.nonce + 1,
      completedUnread: (() => {
        const next = { ...s.completedUnread }
        delete next[tid]
        return next
      })(),
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

  markCompletedUnread: (tid) =>
    set((s) => ({ completedUnread: { ...s.completedUnread, [tid]: true } })),

  clearCompletedUnread: (tid) =>
    set((s) => {
      if (!s.completedUnread[tid]) return s
      const next = { ...s.completedUnread }
      delete next[tid]
      return { completedUnread: next }
    }),

  bumpNonce: () => set((s) => ({ nonce: s.nonce + 1 })),

  resetAll: () =>
    set({
      threadsByModule: {},
      currentThreadByModule: initialCurrent,
      loading: false,
      error: "",
      copiedThreadId: null,
      completedUnread: {},
      nonce: 0,
    }),
}))
