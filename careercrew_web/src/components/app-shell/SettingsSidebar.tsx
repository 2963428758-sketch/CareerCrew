import { useSyncExternalStore } from "react"
import { useNavigate } from "react-router-dom"
import {
  ArrowLeft, PanelLeftClose,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { BrandMark, ThemeToggle } from "@/components/app-shell/AppSidebar"
import { Tooltip } from "@/components/ui/tooltip"
import { SETTINGS_SECTIONS } from "@/components/app-shell/settingsSections"
import { UserMenu } from "@/components/UserMenu"
import { getAuthSnapshot, subscribeAuth } from "@/lib/auth"

interface SettingsSidebarProps {
  collapsed: boolean
  onToggleCollapsed: () => void
  /** 移动端（<768px）以覆盖抽屉呈现 */
  overlay: boolean
  overlayOpen: boolean
  onOverlayClose: () => void
  section: string
  onSelectSection: (key: string) => void
}

/**
 * 设置页侧边栏：与主侧边栏同一套外壳结构——品牌行在顶部，
 * 「返回主页」为主操作，设置区块导航在中间，用户区 + 主题切换在底部。
 * 与主侧边栏一样位于白色圆角工作区之外，直接长在暖灰外壳上。
 */
export function SettingsSidebar({
  collapsed, onToggleCollapsed, overlay, overlayOpen, onOverlayClose,
  section, onSelectSection,
}: SettingsSidebarProps) {
  const navigate = useNavigate()
  const compact = collapsed && !overlay
  const auth = useSyncExternalStore(subscribeAuth, getAuthSnapshot, getAuthSnapshot)
  // 非管理员隐藏 adminOnly 区块（用户管理等）
  const sections = SETTINGS_SECTIONS.filter((s) => !s.adminOnly || auth.user?.role === "admin")

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
        {/* 品牌行（与主侧边栏一致） */}
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

        {/* 主操作：返回主页 */}
        <div className="px-2">
          <Tooltip label={compact ? "返回主页" : undefined}>
            <button
              onClick={() => { navigate("/"); onOverlayClose() }}
              aria-label={compact ? "返回主页" : undefined}
              className={cn(
                "flex w-full items-center rounded-[7px] text-[13px] font-medium text-ink transition-colors duration-100 hover:bg-[var(--hover)]",
                compact ? "h-[34px] justify-center" : "h-[34px] gap-[9px] px-[9px]"
              )}
            >
              <ArrowLeft className="h-4 w-4 shrink-0 text-ink-soft" strokeWidth={1.7} />
              {!compact && <span className="flex-1 text-left">返回主页</span>}
            </button>
          </Tooltip>
        </div>

        {/* 设置导航 */}
        {compact ? (
          <div className="mt-3" />
        ) : (
          <p className="mb-[5px] mt-4 px-[11px] text-[11px] font-medium text-ink-faint">设置</p>
        )}
        <div className="flex flex-col gap-[2px] px-2">
          {sections.map((s) => (
            <Tooltip key={s.key} label={compact ? s.label : undefined}>
              <button
                onClick={() => { onSelectSection(s.key); onOverlayClose() }}
                aria-label={compact ? s.label : undefined}
                className={cn(
                "flex items-center rounded-[7px] font-[450] transition-colors duration-100",
                compact ? "h-[34px] justify-center" : "h-[34px] gap-[9px] px-[9px] text-[13px]",
                section === s.key
                  ? "bg-[var(--active)] text-ink"
                  : "text-ink-soft hover:bg-[var(--hover)] hover:text-ink"
              )}
            >
              <s.icon
                className={cn("h-4 w-4 shrink-0", section === s.key ? "text-ink" : "text-ink-faint")}
                strokeWidth={1.7}
              />
              {!compact && s.label}
              </button>
            </Tooltip>
          ))}
        </div>

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
