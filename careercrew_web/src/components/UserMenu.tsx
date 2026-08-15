import { useEffect, useRef, useState, useSyncExternalStore } from "react"
import { useNavigate } from "react-router-dom"
import { ChevronUp, LogOut, Settings, ShieldCheck } from "lucide-react"
import { getAuthSnapshot, logout, subscribeAuth } from "@/lib/auth"
import { useAvatar } from "@/lib/avatar"
import { cn } from "@/lib/utils"
import { Tooltip } from "@/components/ui/tooltip"

/** 头像底色：按用户名哈希从品牌色板里取，稳定且不重复（无上传头像时兜底）。 */
const AVATAR_COLORS = ["#0D9488", "#7C3AED", "#D97706", "#BE185D", "#2563EB"]

function avatarColor(username: string) {
  let h = 0
  for (const c of username) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return AVATAR_COLORS[h % AVATAR_COLORS.length]
}

/** 侧边栏左下角的用户区：头像（已上传头像优先）+ 用户名，点击弹出设置/退出登录菜单（Codex 风格：克制、无大卡片）。 */
export function UserMenu({ collapsed = false }: { collapsed?: boolean }) {
  const auth = useSyncExternalStore(subscribeAuth, getAuthSnapshot, getAuthSnapshot)
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  /** 折叠模式下菜单锚点（fixed 定位，避免被侧边栏 overflow-hidden 裁剪） */
  const [menuAnchor, setMenuAnchor] = useState<{ left: number; top: number } | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  const avatarUrl = useAvatar(auth.user?.id)

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

  const toggleMenu = () => {
    const next = !open
    if (next && collapsed && ref.current) {
      const r = ref.current.getBoundingClientRect()
      setMenuAnchor({ left: Math.max(8, r.left), top: r.top - 8 })
    } else if (!next) {
      setMenuAnchor(null)
    }
    setOpen(next)
  }

  const menuContent = (
    <>
      <div className="flex items-center gap-2.5 px-2.5 py-2">
        <AvatarImage
          url={avatarUrl}
          fallbackColor={avatarColor(user.username)}
          initial={initial}
          size="h-8 w-8 text-[13px]"
        />
        <div className="min-w-0">
          <p className="truncate text-[13px] font-medium text-ink">{user.username}</p>
          <p className="flex items-center gap-1 text-[11px] text-ink-faint">
            {user.role === "admin" && <ShieldCheck className="h-3 w-3" />}
            {roleLabel}
          </p>
        </div>
      </div>
      <div className="mx-2.5 my-1 h-px bg-[var(--border-soft)]" />
      <button
        onClick={() => { setOpen(false); navigate("/settings") }}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
      >
        <Settings className="h-3.5 w-3.5 shrink-0" />
        设置
      </button>
      <button
        onClick={() => { setOpen(false); void logout() }}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
      >
        <LogOut className="h-3.5 w-3.5 shrink-0" />
        退出登录
      </button>
    </>
  )

  return (
    <div ref={ref} className="relative w-full">
      <Tooltip label={collapsed ? user.username : undefined}>
        <button
          onClick={toggleMenu}
          aria-label={collapsed ? user.username : undefined}
          className={cn(
            "flex w-full items-center rounded-[7px] text-left transition-colors duration-100",
            collapsed ? "h-[34px] justify-center" : "h-[34px] gap-[9px] px-[9px]",
            open ? "bg-[var(--active)]" : "hover:bg-[var(--hover)]"
          )}
        >
          <AvatarImage
            url={avatarUrl}
            fallbackColor={avatarColor(user.username)}
            initial={initial}
            size="h-6 w-6 text-[11px]"
          />
          {!collapsed && (
            <>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[12.5px] font-medium leading-tight text-ink">{user.username}</span>
                <span className="block truncate text-[11px] leading-tight text-ink-faint">{roleLabel}</span>
              </span>
              <ChevronUp className={cn("h-3.5 w-3.5 shrink-0 text-ink-faint transition-transform duration-100", open && "rotate-180")} />
            </>
          )}
        </button>
      </Tooltip>

      {open && collapsed && menuAnchor && (
        <div
          className="fixed z-50 w-56 overflow-hidden rounded-[9px] border border-[var(--border-soft)] bg-workspace py-1 shadow-popover"
          style={{ left: menuAnchor.left, top: menuAnchor.top, transform: "translateY(-100%)" }}
        >
          {menuContent}
        </div>
      )}
      {open && !collapsed && (
        <div className="absolute bottom-full right-1 z-50 mb-1 overflow-hidden rounded-[9px] border border-[var(--border-soft)] bg-workspace py-1 shadow-popover">
          {menuContent}
        </div>
      )}
    </div>
  )
}

/** 头像圆形：已上传图片优先，否则首字母色块。 */
export function AvatarImage({ url, fallbackColor, initial, size }: {
  url: string | null
  fallbackColor: string
  initial: string
  size: string
}) {
  if (url) {
    return (
      <img
        src={url}
        alt="头像"
        className={cn("shrink-0 rounded-full object-cover", size)}
      />
    )
  }
  return (
    <span
      className={cn("flex shrink-0 items-center justify-center rounded-full font-medium text-white", size)}
      style={{ backgroundColor: fallbackColor }}
    >
      {initial}
    </span>
  )
}
