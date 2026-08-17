import { useEffect, useRef, useState, type ComponentType, type ReactNode } from "react"
import { MoreHorizontal, Search, SquarePen } from "lucide-react"
import { cn } from "@/lib/utils"
import { Tooltip } from "@/components/ui/tooltip"
import { WorkspaceHeader } from "@/components/workspace/WorkspaceHeader"
import { useThreadStore } from "@/store/threadStore"

export interface HeaderMenuItem {
  label: string
  onClick: () => void
  danger?: boolean
  icon?: ComponentType<{ className?: string }>
}

/**
 * 对话页统一头部（与职业规划页一致）：
 * 左侧「模块名 / 当前对话标题」面包屑；右侧 新对话 / 搜索 / 更多 三个 30×30 图标按钮。
 * 更多菜单固定包含「复制会话 ID」，页面专属操作（简历管理、知识库管理、结束面试等）
 * 通过 menuItems 注入。
 */
export function ConversationHeader({
  parent,
  title,
  subtitle,
  threadId,
  onNew,
  onSearch,
  menuItems = [],
  extra,
}: {
  parent: string
  title: string
  subtitle?: string
  threadId: string
  onNew: () => void
  onSearch: () => void
  menuItems?: HeaderMenuItem[]
  /** 图标按钮左侧的独立操作按钮（简历管理、结束面试等） */
  extra?: ReactNode
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [menuOpen])

  const iconBtn =
    "flex h-[30px] w-[30px] items-center justify-center rounded-[7px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"

  return (
    <WorkspaceHeader
      parent={parent}
      title={title}
      subtitle={subtitle}
      actions={
        <div className="flex items-center gap-0.5">
          <Tooltip label="新对话" side="bottom">
            <button type="button" onClick={onNew} aria-label="新对话" className={iconBtn}>
              <SquarePen className="h-4 w-4" strokeWidth={1.7} />
            </button>
          </Tooltip>
          <Tooltip label="搜索" side="bottom">
            <button type="button" onClick={onSearch} aria-label="搜索" className={iconBtn}>
              <Search className="h-4 w-4" strokeWidth={1.7} />
            </button>
          </Tooltip>
          {extra}
          <div ref={ref} className="relative">
            <Tooltip label="更多" side="bottom">
              <button
                type="button"
                onClick={() => setMenuOpen((o) => !o)}
                aria-label="更多"
                className={cn(iconBtn, menuOpen && "bg-[var(--active)] text-ink")}
              >
                <MoreHorizontal className="h-4 w-4" strokeWidth={1.7} />
              </button>
            </Tooltip>
            {menuOpen && (
              <div className="absolute right-0 top-[34px] z-50 w-48 overflow-hidden rounded-[9px] border border-[var(--border-soft)] bg-workspace py-1 shadow-popover">
                <HeaderMenuEntry
                  label="复制会话 ID"
                  onClick={() => {
                    setMenuOpen(false)
                    void useThreadStore.getState().copyThreadId(threadId)
                  }}
                />
                {menuItems.map((item) => (
                  <HeaderMenuEntry
                    key={item.label}
                    label={item.label}
                    icon={item.icon}
                    danger={item.danger}
                    onClick={() => {
                      setMenuOpen(false)
                      item.onClick()
                    }}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      }
    />
  )
}

function HeaderMenuEntry({
  label,
  icon: Icon,
  danger,
  onClick,
}: {
  label: string
  icon?: ComponentType<{ className?: string }>
  danger?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12px] transition-colors duration-100",
        danger
          ? "text-destructive hover:bg-destructive/10"
          : "text-ink-soft hover:bg-[var(--hover)] hover:text-ink"
      )}
    >
      {Icon && <Icon className="h-3.5 w-3.5 shrink-0" />}
      <span className="truncate">{label}</span>
    </button>
  )
}

/** 头部独立图标操作按钮（与 新对话/搜索/更多 同风格，悬浮显示方形气泡提示） */
export function HeaderIconAction({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string
  onClick: () => void
  disabled?: boolean
  children: ReactNode
}) {
  return (
    <Tooltip label={label} side="bottom">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-label={label}
        className="flex h-[30px] w-[30px] items-center justify-center rounded-[7px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink disabled:pointer-events-none disabled:opacity-40"
      >
        {children}
      </button>
    </Tooltip>
  )
}
