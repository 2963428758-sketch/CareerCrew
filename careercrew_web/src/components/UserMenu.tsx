import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react"
import { useNavigate } from "react-router-dom"
import { ChevronUp, LogOut, Pencil, Settings } from "lucide-react"
import { getAuthSnapshot, logout, subscribeAuth } from "@/lib/auth"
import { useAvatar } from "@/lib/avatar"
import { cn } from "@/lib/utils"
import { Tooltip } from "@/components/ui/tooltip"
import { NameEditor } from "@/components/DisplayNameEditor"
import { RoleBadge } from "@/components/RoleBadge"

/** 头像底色：按用户名哈希从品牌色板里取，稳定且不重复（无上传头像时兜底）。 */
const AVATAR_COLORS = ["#0D9488", "#7C3AED", "#D97706", "#BE185D", "#2563EB"]

function avatarColor(username: string) {
  let h = 0
  for (const c of username) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return AVATAR_COLORS[h % AVATAR_COLORS.length]
}

/** 侧边栏左下角的用户区：头像（已上传头像优先）+ 显示名，点击弹出设置/改名/退出登录菜单。 */
export function UserMenu({ collapsed = false }: { collapsed?: boolean }) {
  const auth = useSyncExternalStore(subscribeAuth, getAuthSnapshot, getAuthSnapshot)
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  /** 菜单锚点（fixed 定位，避免被侧边栏 overflow-hidden 裁剪） */
  const [menuAnchor, setMenuAnchor] = useState<{ left: number; top: number; width: number } | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  const avatarUrl = useAvatar(auth.user?.id)
  /** 改名状态（在菜单弹层内联编辑） */
  const [renaming, setRenaming] = useState(false)

  /** 按头像按钮当前位置计算菜单锚点：展开右对齐、折叠贴左侧，均夹在视口内 */
  const anchorMenu = useCallback(() => {
    const r = ref.current?.getBoundingClientRect()
    if (!r) return null
    const width = collapsed ? 256 : 240
    const left = collapsed
      ? Math.max(8, r.left)
      : Math.min(Math.max(r.right - width, 8), window.innerWidth - width - 8)
    return { left, top: r.top - 8, width }
  }, [collapsed])

  // 菜单打开期间：窗口尺寸 / 侧边栏收起状态变化时，跟随头像重新锚定
  useEffect(() => {
    if (!open) return
    const reposition = () => {
      const anchor = anchorMenu()
      if (anchor) setMenuAnchor(anchor)
    }
    reposition()
    window.addEventListener("resize", reposition)
    return () => window.removeEventListener("resize", reposition)
  }, [open, anchorMenu])

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

  const initial = (user.display_name || user.username).charAt(0).toUpperCase()
  const displayName = user.display_name || user.username

  const toggleMenu = () => {
    const next = !open
    if (next) {
      const anchor = anchorMenu()
      if (anchor) setMenuAnchor(anchor)
    } else {
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
        <div className="min-w-0 flex-1">
          {renaming ? (
            <NameEditor current={displayName} onDone={() => setRenaming(false)} />
          ) : (
            <p className="flex items-center gap-1.5 truncate text-[13px] font-medium text-ink">
              <span className="truncate">{displayName}</span>
              <Tooltip label="修改名字">
                <button
                  type="button"
                  onClick={() => setRenaming(true)}
                  aria-label="修改名字"
                  className="shrink-0 rounded-[5px] p-0.5 text-ink-faint transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
                >
                  <Pencil className="h-3 w-3" />
                </button>
              </Tooltip>
            </p>
          )}
          <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-ink-faint">
            <span className="truncate">@{user.username}</span>
            <RoleBadge role={user.role} />
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
      <Tooltip label={collapsed ? displayName : undefined}>
        <button
          onClick={toggleMenu}
          aria-label={collapsed ? displayName : undefined}
          className={cn(
            "relative flex w-full items-center rounded-[7px] text-left transition-colors duration-100",
            collapsed ? "h-[34px] justify-center" : "h-[34px] gap-[9px] px-[9px]",
            open ? "bg-[var(--active)]" : "hover:bg-[var(--hover)]"
          )}
        >
          {collapsed ? (
            /* 头像与角色圆点共同占 32px：圆点在头像右侧，不覆盖头像内容。 */
            <span
              data-testid="collapsed-user-avatar-group"
              className="relative flex h-6 w-8 shrink-0 items-center"
            >
              <AvatarImage
                url={avatarUrl}
                fallbackColor={avatarColor(user.username)}
                initial={initial}
                size="h-6 w-6 text-[11px]"
              />
              <span
                data-testid="collapsed-user-role-indicator"
                aria-hidden="true"
                className="absolute bottom-px right-0 h-2 w-2 rounded-full border border-[var(--shell)]"
                style={{ backgroundColor: user.role === "admin" ? "#0D9488" : "#8F8F8A" }}
              />
            </span>
          ) : (
            <AvatarImage
              url={avatarUrl}
              fallbackColor={avatarColor(user.username)}
              initial={initial}
              size="h-6 w-6 text-[11px]"
            />
          )}
          {!collapsed && (
            <>
              <span className="flex min-w-0 flex-1 items-center gap-1.5">
                <span className="truncate text-[12.5px] font-medium leading-tight text-ink">{displayName}</span>
                <RoleBadge role={user.role} />
              </span>
              <ChevronUp className={cn("h-3.5 w-3.5 shrink-0 text-ink-faint transition-transform duration-100", open && "rotate-180")} />
            </>
          )}
        </button>
      </Tooltip>

      {open && menuAnchor && (
        <div
          className="fixed z-50 overflow-hidden rounded-[9px] border border-[var(--border-soft)] bg-workspace py-1 shadow-popover"
          style={{
            left: menuAnchor.left,
            top: menuAnchor.top,
            width: menuAnchor.width,
            transform: "translateY(-100%)",
          }}
        >
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
