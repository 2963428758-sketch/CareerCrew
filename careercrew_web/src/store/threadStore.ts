import { create } from "zustand"
import { apiFetch } from "@/lib/auth"
import { apiErrorText, networkErrorText } from "@/lib/errors"
import { notifyError } from "@/lib/toastBus"
import { copyText } from "@/components/conversation/copy"

export type ThreadModule = "chat" | "matcher" | "interview" | "knowledge" | "consult" | "resume"

/** 会话检索范围：可见范围 + 可选内容分类（两个正交维度，可同时生效）。 */
export interface RetrievalScope {
  type: "all" | "public" | "private"
  category_id?: string | null
}

/** 把后端返回的 retrieval_scope（含旧格式 {"type":"category",...}）归一化为新模型。 */
const normalizeScope = (raw: unknown): RetrievalScope | null => {
  if (!raw || typeof raw !== "object") return null
  const r = raw as Record<string, unknown>
  let type = String(r.type ?? "all")
  const categoryId = r.category_id ? String(r.category_id) : null
  if (type === "category") type = "all"  // 旧格式：分类即全部范围+分类
  if (type !== "all" && type !== "public" && type !== "private") return null
  return categoryId
    ? { type, category_id: categoryId }
    : { type }
}

export interface ThreadItem {
  thread_id: string
  title: string
  module: string
  pinned: boolean
  retrieval_scope?: RetrievalScope | null
  /** 是否已在后端落库。false=仅本地占位（未发过消息），不显示在侧边栏。 */
  persisted?: boolean
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
  /** legacy remap：把旧 thread_id（legacy）替换为新 UUID，同步线程条目与 currentThreadByModule。 */
  remapLegacyThread: (legacyId: string, newId: string) => void
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
      if (!resp.ok) throw new Error(await apiErrorText(resp, "加载会话列表失败"))
      const data: unknown = await resp.json()
      const list: ThreadItem[] = (Array.isArray(data) ? data : []).map((t) => {
        const tid = String((t as Record<string, unknown>).thread_id || "")
        return {
          thread_id: tid,
          title: String((t as Record<string, unknown>).title || tid),
          module: String((t as Record<string, unknown>).module || inferModule(tid)),
          pinned: Boolean((t as Record<string, unknown>).pinned),
          retrieval_scope: normalizeScope((t as Record<string, unknown>).retrieval_scope),
          persisted: true,
          created_at: String((t as Record<string, unknown>).created_at || ""),
          updated_at: String((t as Record<string, unknown>).updated_at || ""),
          entries: Number((t as Record<string, unknown>).entries || 0),
        }
      })
      const filtered = list.filter((t) => t.module === m)
      set((s) => ({ threadsByModule: { ...s.threadsByModule, [m]: sortThreads(filtered) } }))
    } catch (e) {
      set({ error: networkErrorText(e, "加载会话列表失败") })
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
    const scope = useThreadStore.getState().threadsByModule[m]
      ?.find((t) => t.thread_id === tid)?.retrieval_scope
    set((s) => {
      const list = s.threadsByModule[m] || []
      const item = list.find((t) => t.thread_id === tid)
      // 新会话首条消息：本地立即插入该行（流式期间就能看到脉冲圆点），
      // 后端 PATCH 异步补齐，完成时 bumpNonce 重新拉取对齐。
      const nextList = item
        ? list.map((t) => (t.thread_id === tid ? { ...t, title: trimmed, persisted: true } : t))
        : [...list, { thread_id: tid, title: trimmed, module: m, pinned: false, retrieval_scope: scope, persisted: true }]
      return {
        ...s,
        threadsByModule: {
          ...s.threadsByModule,
          [m]: sortThreads(nextList),
        },
      }
    })
    try {
      const resp = await apiFetch(`/api/threads/${encodeURIComponent(tid)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: trimmed, module: m, retrieval_scope: scope ?? null }),
      })
      if (resp.status === 404) {
        // 首条消息时线程可能还没落库：显式创建并带上当前检索范围
        await apiFetch("/api/threads", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ thread_id: tid, module: m, title: trimmed, retrieval_scope: scope ?? null }),
        })
      } else if (!resp.ok) {
        throw new Error(await apiErrorText(resp, "会话标题保存失败"))
      }
    } catch (e) {
      // 后端未就绪时保留本地标题，但明确提示用户
      notifyError(`${networkErrorText(e, "会话标题保存失败")}，本地已保留`)
    }
  },

  setThreadScope: async (m, tid, scope) => {
    // 乐观更新本地列表：无论该会话是否已在列表中，都落一条本地行，
    // 保证选择器立即反映选中状态（切换会话时也能恢复保存的范围）。
    // 未落库的会话（persisted=false）只保留在本地，不写后端、不显示在侧边栏。
    set((s) => {
      const list = s.threadsByModule[m] || []
      const existing = list.find((t) => t.thread_id === tid)
      const nextList = existing
        ? list.map((t) => (t.thread_id === tid ? { ...t, retrieval_scope: scope } : t))
        : [...list, { thread_id: tid, title: tid, module: m, pinned: false, retrieval_scope: scope, persisted: false }]
      return {
        ...s,
        threadsByModule: { ...s.threadsByModule, [m]: sortThreads(nextList) },
      }
    })
    const row = useThreadStore.getState().threadsByModule[m]?.find((t) => t.thread_id === tid)
    if (!row || row.persisted === false) return  // 仅本地保留，首条消息时随 touchThread 落库
    try {
      const resp = await apiFetch(`/api/threads/${encodeURIComponent(tid)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ retrieval_scope: scope }),
      })
      if (resp.status === 404) {
        // 服务端已不存在：退回本地占位，不再显示在侧边栏
        set((s) => ({
          threadsByModule: {
            ...s.threadsByModule,
            [m]: (s.threadsByModule[m] || []).map((t) =>
              t.thread_id === tid ? { ...t, persisted: false } : t
            ),
          },
        }))
      } else if (!resp.ok) {
        throw new Error(await apiErrorText(resp, "检索范围保存失败"))
      }
    } catch (e) {
      // 后端未就绪：保留本地范围，下轮 fetchThreads 会以服务端为准
      notifyError(`${networkErrorText(e, "检索范围保存失败")}，本地已保留`)
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
      const resp = await apiFetch(`/api/threads/${encodeURIComponent(tid)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: trimmed }),
      })
      if (!resp.ok) throw new Error(await apiErrorText(resp, "重命名失败"))
    } catch (e) {
      // 后端未就绪：保留本地改名，下轮 fetch 可能被覆盖，属可接受降级
      notifyError(`${networkErrorText(e, "重命名失败")}，本地已保留`)
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
      const resp = await apiFetch(`/api/threads/${encodeURIComponent(tid)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pinned }),
      })
      if (!resp.ok) throw new Error(await apiErrorText(resp, "置顶设置保存失败"))
    } catch (e) {
      // 后端未就绪：仅本地生效
      notifyError(networkErrorText(e, "置顶设置保存失败"))
    }
  },

  deleteThread: async (m, tid) => {
    try {
      const resp = await apiFetch(`/api/threads/${encodeURIComponent(tid)}`, { method: "DELETE" })
      if (!resp.ok && resp.status !== 404) throw new Error(await apiErrorText(resp, "删除会话失败"))
    } catch (e) {
      // 删除失败也先移除本地项，保持列表即时响应
      notifyError(`${networkErrorText(e, "删除会话失败")}，已从本地列表移除`)
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
    if (!(await copyText(tid))) {
      notifyError(`复制失败，会话 ID：${tid}`)
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

  remapLegacyThread: (legacyId, newId) =>
    set((s) => {
      if (!legacyId || legacyId === newId) return s
      const threadsByModule = { ...s.threadsByModule }
      for (const m of Object.keys(threadsByModule)) {
        const list = threadsByModule[m] || []
        if (list.some((t) => t.thread_id === legacyId)) {
          threadsByModule[m] = list.map((t) =>
            t.thread_id === legacyId ? { ...t, thread_id: newId } : t
          )
        }
      }
      const currentThreadByModule = { ...s.currentThreadByModule }
      for (const m of Object.keys(currentThreadByModule)) {
        if (currentThreadByModule[m] === legacyId) currentThreadByModule[m] = newId
      }
      const completedUnread = { ...s.completedUnread }
      if (completedUnread[legacyId]) {
        delete completedUnread[legacyId]
        completedUnread[newId] = true
      }
      return { threadsByModule, currentThreadByModule, completedUnread }
    }),

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
