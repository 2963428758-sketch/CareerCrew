import { NavLink, useLocation, useNavigate } from "react-router-dom"
import { useEffect, useState, type ComponentType } from "react"
import { MessageSquare, GraduationCap, FileText, Users, Database, Trash2, MessageCircle } from "lucide-react"
import { cn } from "@/lib/utils"
import { useChatStore } from "@/store/chatStore"
import ChatPage from "@/pages/ChatPage"
import InterviewPage from "@/pages/InterviewPage"
import ResumePage from "@/pages/ResumePage"
import ConsultPage from "@/pages/ConsultPage"
import DataPage from "@/pages/DataPage"

const NAV = [
  { to: "/", label: "求职对话", icon: MessageSquare, end: true },
  { to: "/interview", label: "面试练习", icon: GraduationCap },
  { to: "/resume", label: "简历优化", icon: FileText },
  { to: "/consult", label: "会诊", icon: Users },
  { to: "/data", label: "数据看板", icon: Database },
]

const PAGES: Record<string, ComponentType> = {
  "/": ChatPage,
  "/interview": InterviewPage,
  "/resume": ResumePage,
  "/consult": ConsultPage,
  "/data": DataPage,
}

export default function App() {
  const location = useLocation()

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

        <div className="mt-auto p-3">
          <HealthDot />
        </div>
      </nav>

      <main className="flex-1 overflow-hidden">
        {Object.entries(PAGES).map(([path, Page]) => (
          <div key={path} className={cn("h-full", location.pathname === path ? "block" : "hidden")}>
            <Page />
          </div>
        ))}
      </main>
    </div>
  )
}

function ThreadList() {
  const [threads, setThreads] = useState<Record<string, unknown>[]>([])
  const { selectedThreadId, setSelectedThreadId, threadNonce } = useChatStore()
  const navigate = useNavigate()

  const fetchThreads = () => {
    fetch("/api/threads")
      .then((r) => r.json())
      .then((d) => setThreads(d))
      .catch(() => {})
  }

  useEffect(() => { fetchThreads() }, [threadNonce])

  const handleClick = (tid: string) => {
    setSelectedThreadId(tid)
    navigate("/")
  }

  const handleDelete = (e: React.MouseEvent, threadId: string) => {
    e.stopPropagation()
    if (!window.confirm("确定删除这个对话吗？删除后该对话的记忆将无法恢复。")) return
    fetch(`/api/threads/${threadId}`, { method: "DELETE" })
      .then(() => fetchThreads())
  }

  if (threads.length === 0) return null

  return (
    <div className="mt-2 flex-1 overflow-y-auto border-t border-sidebar-border px-3 py-2">
      <p className="mb-1.5 px-1 text-[11px] font-medium text-sidebar-text/70">对话历史</p>
      <div className="space-y-0.5">
        {threads.map((thread) => {
          const tid = String(thread.thread_id || "")
          const title = String(thread.title || tid)
          const count = Number(thread.entries || 0)
          const isActive = selectedThreadId === tid
          return (
            <div
              key={tid}
              className={cn(
                "group flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-[12px] transition-colors",
                isActive ? "bg-sidebar-hover text-white" : "text-sidebar-text hover:bg-sidebar-hover/50 hover:text-white/90"
              )}
              onClick={() => handleClick(tid)}
            >
              <MessageCircle className="h-3 w-3 shrink-0 opacity-60" />
              <span className="flex-1 truncate">{title}</span>
              {count > 0 && <span className="shrink-0 text-[10px] opacity-50">{count}</span>}
              <button
                className="shrink-0 opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                onClick={(e) => handleDelete(e, tid)}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          )
        })}
      </div>
    </div>
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
