import {
  useEffect, useRef, useState, type ComponentType,
} from "react"
import { NavLink, useLocation, useNavigate } from "react-router-dom"
import {
  BookOpen, Copy, FileText, FlaskConical, Gauge, GraduationCap, Loader2, MessageSquare,
  MessageSquareWarning, MoreHorizontal, PanelLeftClose, Pencil, Pin, SquarePen,
  Sun, Moon, Target, Trash2, UserCog, Users,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { isDark, toggleTheme } from "@/lib/theme"
import { CHAT_MODULES, moduleOfPath, useThreadStore, type ThreadItem, type ThreadModule } from "@/store/threadStore"
import { useChatStore } from "@/store/chatStore"
import { IDLE_SESSION, useStreamStore } from "@/store/streamStore"
import { Tooltip } from "@/components/ui/tooltip"
import { ConfirmDialog } from "@/components/ui/ConfirmDialog"
import { UserMenu } from "@/components/UserMenu"
import type { AuthUser } from "@/lib/auth"

const NAV: { to: string; label: string; icon: ComponentType<{ className?: string; strokeWidth?: number }>; end?: boolean; adminOnly?: boolean; reviewerOnly?: boolean }[] = [
  { to: "/", label: "求职规划", icon: MessageSquare, end: true },
  { to: "/matcher", label: "职位匹配", icon: Target },
  { to: "/resume", label: "简历优化", icon: FileText },
  { to: "/interview", label: "面试练习", icon: GraduationCap },
  { to: "/consult", label: "会诊", icon: Users },
  { to: "/knowledge", label: "知识库问答", icon: BookOpen },
  { to: "/quality", label: "质检看板", icon: Gauge, reviewerOnly: true },
  { to: "/quality/bad-cases", label: "坏例处理", icon: MessageSquareWarning, reviewerOnly: true },
  { to: "/quality/eval-cases", label: "评估集", icon: FlaskConical, reviewerOnly: true },
  { to: "/admin/users", label: "用户管理", icon: UserCog, adminOnly: true },
]

/** zustand v5 + React 19：selector 返回新数组会触发 useSyncExternalStore 无限循环，用模块级常量兜底。 */
const EMPTY_THREADS: ThreadItem[] = []

interface AppSidebarProps {
  collapsed: boolean
  onToggleCollapsed: () => void
  /** 移动端（<768px）以覆盖抽屉呈现 */
  overlay: boolean
  overlayOpen: boolean
  onOverlayClose: () => void
  auth: AuthUser | null
}

/**
 * 应用侧边栏（Codex 风格）：直接"长"在暖灰外壳上——无白底、无卡片、无竖分割线。
 * 紧凑导航（34px / 7px 圆角 / 2px 间距）+ 舒展的会话历史 + 底部用户区。
 */
export function AppSidebar({ collapsed, onToggleCollapsed, overlay, overlayOpen, onOverlayClose, auth }: AppSidebarProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const compact = collapsed && !overlay
  /** 质检员是只读审查角色：业务功能（对话/会诊等）后端一律 403，界面整体隐藏 */
  const isReviewer = (auth?.role as string | undefined) === "quality_reviewer"

  /** 新对话：在当前对话模块内开启新会话；若在非会话管理页面则导航至求职规划开启。 */
  const handleNewTask = () => {
    const activeModule = moduleOfPath(location.pathname)
    const targetModule: ThreadModule = activeModule ?? "chat"
    if (targetModule === "chat") {
      useChatStore.getState().newConversation()
    }
    void useThreadStore.getState().registerThread(targetModule)
    if (!activeModule) {
      navigate("/")
    }
    onOverlayClose()
  }

  return (
    <>
      {overlay && overlayOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/25"
          onClick={onOverlayClose}
          aria-hidden
        />
      )}
      <nav
        className={cn(
          "flex flex-col overflow-hidden",
          overlay
            ? cn(
                "fixed bottom-2 left-2 top-2 z-50 w-[244px] rounded-[16px] bg-shell shadow-popover transition-transform duration-[180ms] ease-out",
                overlayOpen ? "translate-x-0" : "-translate-x-[calc(100%+16px)]"
              )
            : cn(
                "relative shrink-0 bg-transparent transition-[width] duration-[180ms] ease-out",
                compact ? "w-14" : "w-[244px]"
              )
        )}
      >
        {/* 品牌行 */}
        <div className={cn("flex h-12 shrink-0 items-center", compact ? "justify-center px-1.5" : "gap-2 px-2.5")}>
          {compact ? (
            <Tooltip label="展开侧边栏">
              <button
                onClick={onToggleCollapsed}
                aria-label="展开侧边栏"
                className="rounded-[7px] p-1.5 text-ink-faint transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
              >
                <BrandMark />
              </button>
            </Tooltip>
          ) : (
            <>
              <BrandMark />
              <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium tracking-[-0.01em] text-ink">
                CareerCrew
              </span>
              {!overlay && (
                <Tooltip label="收起侧边栏">
                  <button
                    onClick={onToggleCollapsed}
                    aria-label="收起侧边栏"
                    className="rounded-[7px] p-1.5 text-ink-faint transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
                  >
                    <PanelLeftClose className="h-4 w-4" strokeWidth={1.7} />
                  </button>
                </Tooltip>
              )}
            </>
          )}
        </div>

        {/* 主操作：新对话（质检员无业务会话权限，隐藏） */}
        {!isReviewer && (
          <div className="px-2">
            <Tooltip label={compact ? "新对话" : undefined}>
              <button
                onClick={handleNewTask}
                aria-label={compact ? "新对话" : undefined}
                className={cn(
                  "flex w-full items-center rounded-[7px] text-[13px] font-medium text-ink transition-colors duration-100 hover:bg-[var(--hover)]",
                  compact ? "h-[34px] justify-center" : "h-[34px] gap-[9px] px-[9px]"
                )}
              >
                <SquarePen className="h-4 w-4 shrink-0 text-ink-soft" strokeWidth={1.7} />
                {!compact && <span className="flex-1 text-left">新对话</span>}
              </button>
            </Tooltip>
          </div>
        )}

        {/* 模块导航 */}
        {compact ? (
          <div className="mt-3" />
        ) : (
          <p className="mb-[5px] mt-4 px-[11px] text-[11px] font-medium text-ink-faint">
            {isReviewer ? "质量审查" : "求职助手"}
          </p>
        )}
        <div className="flex flex-col gap-[2px] px-2">
          {NAV.filter(
            (item) =>
              (!item.adminOnly || auth?.role === "admin") &&
              (!item.reviewerOnly || (auth?.role as string) === "quality_reviewer") &&
              (auth?.role !== "quality_reviewer" || !!item.reviewerOnly)
          ).map((item) => (
            <Tooltip key={item.to} label={compact ? item.label : undefined}>
              <NavLink
                to={item.to}
                end={item.end}
                aria-label={compact ? item.label : undefined}
                onClick={overlay ? onOverlayClose : undefined}
                className={({ isActive }) =>
                  cn(
                    "flex items-center rounded-[7px] font-[450] transition-colors duration-100",
                    compact ? "h-[34px] justify-center" : "h-[34px] gap-[9px] px-[9px] text-[13px]",
                    isActive
                      ? "bg-[var(--active)] text-ink"
                      : "text-ink-soft hover:bg-[var(--hover)] hover:text-ink"
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <item.icon
                      className={cn("h-4 w-4 shrink-0", isActive ? "text-ink" : "text-ink-faint")}
                      strokeWidth={1.7}
                    />
                    {!compact && item.label}
                  </>
                )}
              </NavLink>
            </Tooltip>
          ))}
        </div>

        {/* 对话历史（当前模块；质检员无业务会话，隐藏） */}
        {!compact && !isReviewer && <ThreadList />}

        {/* 底部：用户区 + 主题（设置入口在用户菜单内） */}
        <div className="mt-auto flex shrink-0 flex-col gap-[2px] px-2 pb-2">
          <div className={cn("flex items-center gap-1", compact && "flex-col")}>
            <div className="min-w-0 flex-1">
              <UserMenu collapsed={compact} />
            </div>
            <ThemeToggle />
          </div>
        </div>
      </nav>
    </>
  )
}

export function ThemeToggle() {
  const [dark, setDark] = useState(isDark())
  const label = dark ? "切换到浅色模式" : "切换到深色模式"
  return (
    <Tooltip label={label}>
      <button
        onClick={() => { toggleTheme(); setDark(isDark()) }}
        aria-label={label}
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px] text-ink-faint transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
      >
        {dark ? <Sun className="h-4 w-4" strokeWidth={1.7} /> : <Moon className="h-4 w-4" strokeWidth={1.7} />}
      </button>
    </Tooltip>
  )
}

export function BrandMark() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" className="shrink-0">
      <circle cx="12" cy="5" r="2.5" fill="#0D9488" />
      <circle cx="5" cy="17" r="2.5" fill="#D97706" />
      <circle cx="19" cy="17" r="2.5" fill="#7C3AED" />
      <path d="M12 7.5L5.5 14.5M12 7.5L18.5 14.5M7 17h10" stroke="#2D3340" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  )
}

// ── 对话历史 ──

function ThreadList() {
  const navigate = useNavigate()
  const location = useLocation()
  const module = moduleOfPath(location.pathname)
  const {
    threadsByModule, currentThreadByModule, loading, error, copiedThreadId, nonce,
    setActiveModule, fetchThreads, selectThread, renameThread, togglePin, deleteThread, copyThreadId,
  } = useThreadStore()
  /** 待删除确认的会话（自定义 Codex 确认框，替代 window.confirm） */
  const [confirmDelete, setConfirmDelete] = useState<ThreadItem | null>(null)

  useEffect(() => {
    if (module) {
      setActiveModule(module)
      fetchThreads(module)
    }
  }, [module, nonce, fetchThreads, setActiveModule])

  if (!module) return <div className="flex-1" />

  // 只显示已落库的会话；未发过消息的本地占位（persisted=false）不占侧边栏
  const threads = (threadsByModule[module] ?? EMPTY_THREADS).filter((t) => t.persisted !== false)
  const currentId = currentThreadByModule[module]
  const moduleMeta = CHAT_MODULES.find((m) => m.key === module)!

  const handleSelect = (tid: string) => {
    selectThread(module, tid)
    navigate(moduleMeta.path)
  }

  const handleDelete = (tid: string) => {
    deleteThread(module, tid)
  }

  return (
    <div className="mt-1 flex min-h-0 flex-1 flex-col">
      <p className="mb-[5px] px-[11px] text-[11px] font-medium text-ink-faint">对话历史</p>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {loading ? (
          <p className="px-[9px] py-1 text-[11px] text-ink-faint">加载中…</p>
        ) : error ? (
          <div className="px-[9px] py-1">
            <p className="text-[11px] text-destructive/80">{error}</p>
            <button
              onClick={() => fetchThreads(module)}
              className="mt-1 text-[11px] text-ink-faint underline underline-offset-2 transition-colors duration-100 hover:text-ink"
            >
              点击重试
            </button>
          </div>
        ) : threads.length === 0 ? (
          <p className="px-[9px] py-1 text-[11px] text-ink-faint">暂无会话</p>
        ) : (
          <div className="flex flex-col gap-[2px]">
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
                onDelete={() => setConfirmDelete(thread)}
                onCopy={() => copyThreadId(thread.thread_id)}
              />
            ))}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={confirmDelete !== null}
        title="删除这个对话？"
        message={`「${confirmDelete?.title ?? ""}」删除后，该对话的记忆将无法恢复。`}
        onConfirm={() => confirmDelete && handleDelete(confirmDelete.thread_id)}
        onClose={() => setConfirmDelete(null)}
      />
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
  // 会话流状态：streaming=转圈圈，done+未点击=圆点（点击后清除），error=红色
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
          "group flex cursor-pointer items-center gap-1.5 rounded-[7px] px-[9px] py-[5px] text-[12px] leading-tight transition-colors duration-100",
          isActive ? "bg-[var(--active)] text-ink" : "text-ink-soft hover:bg-[var(--hover)] hover:text-ink"
        )}
        onClick={() => {
          setMenuOpen(false)
          onSelect()
        }}
      >
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
            className="min-w-0 flex-1 rounded-[5px] border border-input bg-workspace px-1.5 py-0.5 text-[12px] text-ink outline-none"
          />
        ) : (
          <>
            {thread.pinned && <Pin className="h-3 w-3 shrink-0 text-primary" />}
            {session.status === "streaming" && (
              <Tooltip label="正在生成回答…">
                <span className="flex shrink-0">
                  <Loader2 className="h-3 w-3 animate-spin text-ink-faint" />
                </span>
              </Tooltip>
            )}
            {session.status === "done" && unread && (
              <Tooltip label="回答完成，点击查看">
                <span
                  className="h-1.5 w-1.5 shrink-0 rounded-full bg-[color:var(--ink)] opacity-60"
                />
              </Tooltip>
            )}
            {session.status === "error" && (
              <Tooltip label="生成出错">
                <span
                  className="h-1.5 w-1.5 shrink-0 rounded-full bg-destructive/70"
                />
              </Tooltip>
            )}
            <span className="min-w-0 flex-1 truncate">{thread.title}</span>
            <Tooltip label="更多操作">
              <button
                className="shrink-0 rounded-[5px] p-0.5 opacity-0 transition-opacity duration-100 hover:bg-[var(--hover)] group-hover:opacity-100"
                onClick={(e) => {
                  e.stopPropagation()
                  setMenuOpen((o) => !o)
                }}
                aria-label="更多操作"
              >
                <MoreHorizontal className="h-3.5 w-3.5" />
              </button>
            </Tooltip>
          </>
        )}
      </div>

      {menuOpen && !renaming && (
        <div className="absolute right-0 top-6 z-40 w-36 overflow-hidden rounded-[9px] border border-[var(--border-soft)] bg-workspace py-1 shadow-popover">
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
        "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12px] transition-colors duration-100",
        danger
          ? "text-destructive hover:bg-destructive/10"
          : "text-ink-soft hover:bg-[var(--hover)] hover:text-ink"
      )}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{label}</span>
    </button>
  )
}
