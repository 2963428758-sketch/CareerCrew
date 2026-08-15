import { NavLink, useLocation, useNavigate } from "react-router-dom"
import { lazy, Suspense, useEffect, useRef, useState, useSyncExternalStore, type ComponentType } from "react"
import {
  BookOpen, Copy, FileText, GraduationCap, MessageCircle,
  Loader2, MessageSquare, MoreHorizontal, PanelLeftClose, Pencil, Pin, Target, Trash2, UserCog, Users,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { CHAT_MODULES, moduleOfPath, useThreadStore, type ThreadItem, type ThreadModule } from "@/store/threadStore"
import { IDLE_SESSION, useStreamStore } from "@/store/streamStore"
import { UserMenu } from "@/components/UserMenu"
import { AuthLoading, AuthScreen } from "@/components/AuthScreen"
import PasswordChangeScreen from "@/components/PasswordChangeScreen"
import { getAuthSnapshot, restoreSession, subscribeAuth } from "@/lib/auth"

// 路由懒加载：按页拆 chunk，消除首屏大 bundle（Chat/Consult/Knowledge 等重页面按需加载）
const ChatPage = lazy(() => import("@/pages/ChatPage"))
const MatcherPage = lazy(() => import("@/pages/MatcherPage"))
const InterviewPage = lazy(() => import("@/pages/InterviewPage"))
const ResumePage = lazy(() => import("@/pages/ResumePage"))
const KnowledgePage = lazy(() => import("@/pages/KnowledgePage"))
const ConsultPage = lazy(() => import("@/pages/ConsultPage"))
const DataPage = lazy(() => import("@/pages/DataPage"))
const SettingsPage = lazy(() => import("@/pages/SettingsPage"))
const AdminUsersPage = lazy(() => import("@/pages/AdminUsersPage"))

const NAV: { to: string; label: string; icon: ComponentType<{ className?: string }>; end?: boolean; adminOnly?: boolean }[] = [
  { to: "/", label: "求职规划", icon: MessageSquare, end: true },
  { to: "/matcher", label: "职位匹配", icon: Target },
  { to: "/resume", label: "简历优化", icon: FileText },
  { to: "/interview", label: "面试练习", icon: GraduationCap },
  { to: "/consult", label: "会诊", icon: Users },
  { to: "/knowledge", label: "知识库问答", icon: BookOpen },
  { to: "/admin/users", label: "用户管理", icon: UserCog, adminOnly: true },
]

const PAGES: Record<string, ComponentType> = {
  "/": ChatPage,
  "/matcher": MatcherPage,
  "/interview": InterviewPage,
  "/resume": ResumePage,
  "/knowledge": KnowledgePage,
  "/consult": ConsultPage,
  "/data": DataPage,
  "/settings": SettingsPage,
  "/admin/users": AdminUsersPage,
}

/** zustand v5 + React 19：selector 返回新数组会触发 useSyncExternalStore 无限循环，用模块级常量兜底。 */
const EMPTY_THREADS: ThreadItem[] = []

export default function App() {
  const auth = useSyncExternalStore(subscribeAuth, getAuthSnapshot, getAuthSnapshot)
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => { void restoreSession() }, [])

  // 登出/切换用户：清空会话与线程状态（各 store 里可能残留上一个用户的数据）
  const userId = auth.user?.id
  useEffect(() => {
    useThreadStore.getState().resetAll()
    useStreamStore.getState().resetAll()
  }, [userId])

  if (auth.status === "loading") return <AuthLoading />
  if (auth.status === "anonymous") return <AuthScreen />
  // 新建/重置密码的账号：完成强制改密前只能看到改密页（后端业务 API 同步 403 兜底）
  if (auth.user?.must_change_password) return <PasswordChangeScreen />

  // 设置页是独立页面：不渲染主侧边栏（页面自带设置导航侧边栏）
  const isSettings = location.pathname === "/settings"

  return (
    <div className="flex h-screen overflow-hidden">
      {!isSettings && (
        <nav className={cn("relative flex shrink-0 flex-col bg-sidebar transition-[width] duration-200", collapsed ? "w-14" : "w-56")}>
          <div className={cn("flex h-16 shrink-0 items-center border-b border-sidebar-border", collapsed ? "justify-center px-2" : "gap-2.5 px-4")}>
            {collapsed ? (
              <button
                onClick={() => setCollapsed(false)}
                className="rounded-md p-1.5 text-sidebar-text transition-colors hover:bg-sidebar-hover hover:text-white"
                title="展开侧边栏"
              >
                <BrandMark />
              </button>
            ) : (
              <>
                <BrandMark />
                <span className="min-w-0 flex-1 truncate font-display text-[17px] font-bold text-white tracking-tight">CareerCrew</span>
                <button
                  onClick={() => setCollapsed(true)}
                  className="rounded-md p-1.5 text-sidebar-text transition-colors hover:bg-sidebar-hover hover:text-white"
                  title="收起侧边栏"
                >
                  <PanelLeftClose className="h-4 w-4" />
                </button>
              </>
            )}
          </div>

          <div className={cn("flex flex-col gap-0.5", collapsed ? "p-2" : "p-3")}>
            {NAV.filter((item) => !item.adminOnly || auth.user?.role === "admin").map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                title={collapsed ? item.label : undefined}
                className={({ isActive }) =>
                  cn(
                    "group relative flex items-center rounded-md transition-all",
                    collapsed ? "justify-center py-2.5" : "gap-3 px-3 py-2.5 text-[13px] font-medium",
                    isActive
                      ? "bg-sidebar-hover text-white"
                      : "text-sidebar-text hover:bg-sidebar-hover/50 hover:text-white/90"
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    {isActive && (
                      <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r bg-sidebar-active" />
                    )}
                    <item.icon className="h-4 w-4 shrink-0" />
                    {!collapsed && item.label}
                  </>
                )}
              </NavLink>
            ))}
          </div>

          {/* 对话历史 */}
          {!collapsed && <ThreadList />}

          {/* 用户区：头像 + 用户名，点击弹出设置/退出登录 */}
          <UserMenu collapsed={collapsed} />
        </nav>
      )}

      <main className="flex-1 overflow-hidden">
        <Suspense
          fallback={
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              页面加载中…
            </div>
          }
        >
          {isSettings ? (
            <SettingsPage />
          ) : (
            (() => {
              const requested = PAGES[location.pathname] ?? ChatPage
              const Page =
                location.pathname === "/admin/users" && auth.user?.role !== "admin"
                  ? ChatPage
                  : requested
              return <Page key={location.pathname} />
            })()
          )}
        </Suspense>
      </main>
    </div>
  )
}

function BrandMark() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" className="shrink-0">
      <circle cx="12" cy="5" r="2.5" fill="#0D9488" />
      <circle cx="5" cy="17" r="2.5" fill="#D97706" />
      <circle cx="19" cy="17" r="2.5" fill="#7C3AED" />
      <path d="M12 7.5L5.5 14.5M12 7.5L18.5 14.5M7 17h10" stroke="#2D3340" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  )
}

function ThreadList() {
  const navigate = useNavigate()
  const location = useLocation()
  const module = moduleOfPath(location.pathname)
  const {
    threadsByModule, currentThreadByModule, loading, error, copiedThreadId, nonce,
    setActiveModule, fetchThreads, selectThread, renameThread, togglePin, deleteThread, copyThreadId,
  } = useThreadStore()

  useEffect(() => {
    if (module) {
      setActiveModule(module)
      fetchThreads(module)
    }
  }, [module, nonce, fetchThreads, setActiveModule])

  if (!module) return null

  const threads = threadsByModule[module] ?? EMPTY_THREADS
  const currentId = currentThreadByModule[module]
  const moduleMeta = CHAT_MODULES.find((m) => m.key === module)!

  const handleSelect = (tid: string) => {
    selectThread(module, tid)
    navigate(moduleMeta.path)
  }

  const handleDelete = (tid: string) => {
    if (!window.confirm("确定删除这个对话吗？删除后该对话的记忆将无法恢复。")) return
    deleteThread(module, tid)
  }

  return (
    <div className="mt-2 flex-1 overflow-y-auto border-t border-sidebar-border px-3 py-2">
      <p className="mb-1.5 px-1 text-[11px] font-medium text-sidebar-text/70">对话历史</p>
      {loading ? (
        <p className="px-1 py-1 text-[11px] text-sidebar-text/60">加载中…</p>
      ) : error ? (
        <p className="px-1 py-1 text-[11px] text-red-400/80">会话加载失败</p>
      ) : threads.length === 0 ? (
        <p className="px-1 py-1 text-[11px] text-sidebar-text/60">暂无会话</p>
      ) : (
      <div className="space-y-0.5">
        {threads.map((thread) => (
          <ThreadRow
            key={thread.thread_id}
            module={module}
            thread={thread}
            isActive={currentId === thread.thread_id}
            copied={copiedThreadId === thread.thread_id}
            onSelect={() => handleSelect(thread.thread_id)}
            onRename={(title) => renameThread(module, thread.thread_id, title)}
            onTogglePin={(pinned) => togglePin(module, thread.thread_id, pinned)}
            onDelete={() => handleDelete(thread.thread_id)}
            onCopy={() => copyThreadId(thread.thread_id)}
          />
        ))}
      </div>
      )}
    </div>
  )
}

function ThreadRow({ module: _module, thread, isActive, copied, onSelect, onRename, onTogglePin, onDelete, onCopy }: {
  module: ThreadModule
  thread: ThreadItem
  isActive: boolean
  copied: boolean
  onSelect: () => void
  onRename: (title: string) => void
  onTogglePin: (pinned: boolean) => void
  onDelete: () => void
  onCopy: () => void
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [draft, setDraft] = useState(thread.title)
  const ref = useRef<HTMLDivElement>(null)
  // 会话流状态：streaming=转圈圈，done+未点击=蓝色圆点（点击后清除），error=红色
  const session = useStreamStore((s) => s.sessions[thread.thread_id]) ?? IDLE_SESSION
  const unread = useThreadStore((s) => !!s.completedUnread[thread.thread_id])

  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [menuOpen])

  const commitRename = () => {
    const title = draft.trim()
    if (title && title !== thread.title) onRename(title)
    setRenaming(false)
  }

  return (
    <div ref={ref} className="relative">
      <div
        className={cn(
          "group flex cursor-pointer items-center gap-1.5 rounded-md px-2 py-1.5 text-[12px] transition-colors",
          isActive ? "bg-sidebar-hover text-white" : "text-sidebar-text hover:bg-sidebar-hover/50 hover:text-white/90"
        )}
        onClick={() => {
          setMenuOpen(false)
          onSelect()
        }}
      >
        <MessageCircle className={cn("h-3 w-3 shrink-0 opacity-60", thread.pinned && "text-sidebar-text-active")} />
        {renaming ? (
          <input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename()
              if (e.key === "Escape") setRenaming(false)
            }}
            onBlur={commitRename}
            onClick={(e) => e.stopPropagation()}
            className="min-w-0 flex-1 rounded border border-sidebar-border bg-sidebar px-1.5 py-0.5 text-[12px] text-white outline-none"
          />
        ) : (
          <>
            {thread.pinned && <Pin className="h-3 w-3 shrink-0 text-sidebar-text-active" />}
            {session.status === "streaming" && (
              <span className="flex shrink-0" title="正在生成回答…">
                <Loader2 className="h-3 w-3 animate-spin" style={{ color: "#F59E0B" }} />
              </span>
            )}
            {session.status === "done" && unread && (
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: "#3B82F6", boxShadow: "0 0 5px #3B82F6" }}
                title="回答完成，点击查看"
              />
            )}
            {session.status === "error" && (
              <span
                className="h-1.5 w-1.5 shrink-0 rounded-full"
                style={{ backgroundColor: "#EF4444" }}
                title="生成出错"
              />
            )}
            <span className="min-w-0 flex-1 truncate">{thread.title}</span>
            <button
              className="shrink-0 rounded p-0.5 opacity-0 transition-opacity hover:bg-sidebar-hover group-hover:opacity-100"
              onClick={(e) => {
                e.stopPropagation()
                setMenuOpen((o) => !o)
              }}
              title="更多操作"
            >
              <MoreHorizontal className="h-3.5 w-3.5" />
            </button>
          </>
        )}
      </div>

      {menuOpen && !renaming && (
        <div className="absolute right-0 top-5 z-40 w-36 overflow-hidden rounded-md border border-sidebar-border bg-[#1E242E] py-1 shadow-xl">
          <MenuItem icon={Pin} label={thread.pinned ? "取消置顶" : "置顶"} onClick={() => { setMenuOpen(false); onTogglePin(!thread.pinned) }} />
          <MenuItem icon={Pencil} label="重命名" onClick={() => { setMenuOpen(false); setRenaming(true); setDraft(thread.title) }} />
          <MenuItem icon={Copy} label={copied ? "已复制 ✓" : "复制会话 ID"} onClick={onCopy} />
          <MenuItem icon={Trash2} label="删除" danger onClick={() => { setMenuOpen(false); onDelete() }} />
        </div>
      )}
    </div>
  )
}

function MenuItem({ icon: Icon, label, onClick, danger }: {
  icon: ComponentType<{ className?: string }>
  label: string
  onClick: () => void
  danger?: boolean
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12px] transition-colors",
        danger
          ? "text-red-400 hover:bg-red-500/10"
          : "text-sidebar-text hover:bg-sidebar-hover hover:text-white"
      )}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{label}</span>
    </button>
  )
}
