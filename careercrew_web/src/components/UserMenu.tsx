import { useEffect, useRef, useState, useSyncExternalStore } from "react"
import { useNavigate } from "react-router-dom"
import { ChevronUp, LogOut, Settings, ShieldCheck } from "lucide-react"
import { getAuthSnapshot, logout, subscribeAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

/** 头像底色：按用户名哈希从品牌色板里取，稳定且不重复。 */
const AVATAR_COLORS = ["#0D9488", "#7C3AED", "#D97706", "#BE185D", "#2563EB"]

function avatarColor(username: string) {
  let h = 0
  for (const c of username) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return AVATAR_COLORS[h % AVATAR_COLORS.length]
}

/** 侧边栏左下角的用户区：头像 + 用户名，点击弹出设置/退出登录菜单（Codex 风格）。 */
export function UserMenu({ collapsed = false }: { collapsed?: boolean }) {
  const auth = useSyncExternalStore(subscribeAuth, getAuthSnapshot, getAuthSnapshot)
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [open])

  const user = auth.user
  if (!user) return null

  const initial = user.username.charAt(0).toUpperCase()
  const roleLabel = user.role === "admin" ? "管理员" : "普通用户"

  return (
    <div ref={ref} className="relative mt-auto border-t border-sidebar-border px-1.5 pb-1.5 pt-1.5">
      <button
        onClick={() => setOpen((o) => !o)}
        title={collapsed ? user.username : undefined}
        className={cn(
          "flex w-full items-center gap-2 rounded-md text-left transition-colors",
          collapsed ? "justify-center px-1 py-1.5" : "px-2 py-1.5",
          open ? "bg-sidebar-hover" : "hover:bg-sidebar-hover/60"
        )}
      >
        <span
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold text-white"
          style={{ backgroundColor: avatarColor(user.username) }}
        >
          {initial}
        </span>
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-medium leading-tight text-white">{user.username}</span>
              <span className="block truncate text-[11px] leading-tight text-sidebar-text">{roleLabel}</span>
            </span>
            <ChevronUp className={cn("h-3.5 w-3.5 shrink-0 text-sidebar-text transition-transform", open && "rotate-180")} />
          </>
        )}
      </button>

      {open && (
        <div className={cn(
          "absolute bottom-full left-1.5 z-50 mb-1.5 overflow-hidden rounded-lg border border-sidebar-border bg-[#1E242E] py-1 shadow-xl",
          collapsed ? "w-56" : "right-1.5"
        )}>
          <div className="flex items-center gap-2.5 px-2.5 py-2">
            <span
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold text-white"
              style={{ backgroundColor: avatarColor(user.username) }}
            >
              {initial}
            </span>
            <div className="min-w-0">
              <p className="truncate text-[13px] font-medium text-white">{user.username}</p>
              <p className="flex items-center gap-1 text-[11px] text-sidebar-text">
                {user.role === "admin" && <ShieldCheck className="h-3 w-3" />}
                {roleLabel}
              </p>
            </div>
          </div>
          <div className="mx-2.5 my-1 h-px bg-sidebar-border" />
          <button
            onClick={() => { setOpen(false); navigate("/settings") }}
            className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px] text-sidebar-text transition-colors hover:bg-sidebar-hover hover:text-white"
          >
            <Settings className="h-3.5 w-3.5 shrink-0" />
            设置
          </button>
          <button
            onClick={() => { setOpen(false); void logout() }}
            className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px] text-sidebar-text transition-colors hover:bg-sidebar-hover hover:text-white"
          >
            <LogOut className="h-3.5 w-3.5 shrink-0" />
            退出登录
          </button>
        </div>
      )}
    </div>
  )
}
