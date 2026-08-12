import { NavLink, useLocation, useNavigate } from "react-router-dom"
import { useEffect, useRef, useState, type ComponentType } from "react"
import {
  BookOpen, ChevronDown, Copy, FileText, GraduationCap, MessageCircle,
  MessageSquare, MoreHorizontal, Pencil, Pin, Settings, Target, Trash2, Users,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { CHAT_MODULES, moduleOfPath, useThreadStore, type ThreadItem, type ThreadModule } from "@/store/threadStore"
import { SettingsDialog } from "@/components/SettingsDialog"
import ChatPage from "@/pages/ChatPage"
import InterviewPage from "@/pages/InterviewPage"
import ResumePage from "@/pages/ResumePage"
import ConsultPage from "@/pages/ConsultPage"
import DataPage from "@/pages/DataPage"
import KnowledgePage from "@/pages/KnowledgePage"
import MatcherPage from "@/pages/MatcherPage"

const NAV = [
  { to: "/", label: "求职对话", icon: MessageSquare, end: true },
  { to: "/matcher", label: "职位匹配", icon: Target },
  { to: "/interview", label: "面试练习", icon: GraduationCap },
  { to: "/resume", label: "简历优化", icon: FileText },
  { to: "/knowledge", label: "知识库问答", icon: BookOpen },
  { to: "/consult", label: "会诊", icon: Users },
]

const PAGES: Record<string, ComponentType> = {
  "/": ChatPage,
  "/matcher": MatcherPage,
  "/interview": InterviewPage,
  "/resume": ResumePage,
  "/knowledge": KnowledgePage,
  "/consult": ConsultPage,
  "/data": DataPage,
}

export default function App() {
  const location = useLocation()
  const [settingsOpen, setSettingsOpen] = useState(false)

  return (
    <div className="flex h-screen overflow-hidden">
      <nav className="flex w-56 shrink-0 flex-col bg-sidebar">
        <div className="flex h-16 items-center gap-2.5 border-b border-sidebar-border px-5">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" className="shrink-0">
            <circle cx="12" cy="5" r="2.5" fill="#0D9488" />
            <circle cx="5" cy="17" r="2.5" fill="#D97706" />
            <circle cx="19" cy="17" r="2.5" fill="#7C3AED" />
            <path d="M12 7.5L5.5 14.5M12 7.5L18.5 14.5M7 17h10" stroke="#2D3340" strokeWidth="1.2" strokeLinecap="round" />
          </svg>
          <span className="font-display text-[17px] font-bold text-white tracking-tight">CareerCrew</span>
        </div>

        <div className="flex flex-col gap-0.5 p-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "group relative flex items-center gap-3 rounded-md px-3 py-2.5 text-[13px] font-medium transition-all",
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
                  {item.label}
                </>
              )}
            </NavLink>
          ))}
        </div>

        {/* 对话历史 */}
        <ThreadList />

        <div className="mt-auto flex items-center justify-between gap-1 border-t border-sidebar-border py-1 pl-1 pr-2">
          <HealthDot />
          <button
            onClick={() => setSettingsOpen(true)}
            className="rounded-md p-2 text-sidebar-text transition-colors hover:bg-sidebar-hover hover:text-white"
            title="设置"
          >
            <Settings className="h-4 w-4" />
          </button>
        </div>
      </nav>

      <main className="flex-1 overflow-hidden">
        {Object.entries(PAGES).map(([path, Page]) => (
          <div key={path} className={cn("h-full", location.pathname === path ? "block" : "hidden")}>
            <Page />
          </div>
        ))}
      </main>

      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
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

  const threads = threadsByModule[module] ?? []
  const currentId = currentThreadByModule[module]
  const moduleMeta = CHAT_MODULES.find((m) => m.key === module)!

  const handleSelectModule = (m: ThreadModule) => {
    setActiveModule(m)
    navigate(CHAT_MODULES.find((x) => x.key === m)!.path)
  }

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
      <ModuleDropdown module={module} onSelect={handleSelectModule} />
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

function ModuleDropdown({ module, onSelect }: { module: ThreadModule; onSelect: (m: ThreadModule) => void }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const label = CHAT_MODULES.find((m) => m.key === module)?.label || module

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [open])

  return (
    <div ref={ref} className="relative mb-1.5">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-[12px] text-sidebar-text transition-colors hover:bg-sidebar-hover/50 hover:text-white/90"
      >
        <span className="truncate">{label}</span>
        <ChevronDown className={cn("h-3.5 w-3.5 shrink-0 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="absolute left-0 right-0 z-40 mt-1 overflow-hidden rounded-md border border-sidebar-border bg-[#1E242E] py-1 shadow-xl">
          {CHAT_MODULES.map((m) => (
            <button
              key={m.key}
              onClick={() => {
                onSelect(m.key)
                setOpen(false)
              }}
              className={cn(
                "block w-full px-2.5 py-1.5 text-left text-[12px] transition-colors",
                m.key === module
                  ? "bg-sidebar-hover text-white"
                  : "text-sidebar-text hover:bg-sidebar-hover/50 hover:text-white/90"
              )}
            >
              {m.label}
            </button>
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

function HealthDot() {
  const [status, setStatus] = useState<"checking" | "ok" | "down">("checking")

  useEffect(() => {
    const check = () => {
      fetch("/api/health")
        .then((r) => r.json())
        .then((d) => setStatus(d.status === "ok" ? "ok" : "down"))
        .catch(() => setStatus("down"))
    }
    check()
    const t = setInterval(check, 30000)
    return () => clearInterval(t)
  }, [])

  const color = status === "ok" ? "#0D9488" : status === "down" ? "#EF4444" : "#78716C"
  const label = status === "ok" ? "服务正常" : status === "down" ? "服务异常" : "连接中…"

  return (
    <div className="flex items-center gap-2 px-3 py-2 text-[11px] text-sidebar-text">
      <span
        className="h-2 w-2 rounded-full"
        style={{ backgroundColor: color, boxShadow: status === "ok" ? `0 0 6px ${color}` : "none" }}
      />
      {label}
    </div>
  )
}
