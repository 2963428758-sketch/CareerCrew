import { useEffect, useState } from "react"
import { cn } from "@/lib/utils"
import { Tooltip } from "@/components/ui/tooltip"

/** Rail 允许占用的最大高度：视口高度的一半 */
const MAX_RAIL_RATIO = 0.5
/** 横条行的尺寸区间（px）：少量对话宽松，多对话自动压缩 */
const MAX_ROW = 16
const MIN_ROW = 4
/** 滑窗模式的固定行高与窗口上限 */
const WINDOW_ROW = 9
const WINDOW_CAP = 48

/** 宽松结构类型：各对话页的消息 content 可为可选字段 */
export interface RailTurn {
  id: string
  user: { content?: string }
}

type RailLayout =
  | { kind: "all"; row: number; turns: RailTurn[] }
  | { kind: "window"; row: number; turns: RailTurn[]; start: number; end: number; total: number }

/**
 * 计算 Rail 布局：
 * - 全部横条 1:1 对应对话轮次；行高随轮数在 16px ~ 4px 间自适应压缩，
 *   保证整个横条簇始终不超过视口高度的一半，全部可点。
 * - 轮次多到最小行高也放不下（约 100+ 轮）时进入滑窗模式：
 *   只显示以当前激活轮为中心的窗口（≤48 条），窗口随滚动位置自动跟随，
 *   上下边缘的淡色边条用于翻到前/后一段。
 */
function railLayout(turns: RailTurn[], activeTurnId: string | null, viewportHeight: number): RailLayout {
  const n = turns.length
  const avail = Math.max(160, Math.round(viewportHeight * MAX_RAIL_RATIO))

  if (n * MIN_ROW <= avail) {
    const row = Math.max(MIN_ROW, Math.min(MAX_ROW, Math.floor(avail / n)))
    return { kind: "all", row, turns }
  }

  const cap = Math.min(WINDOW_CAP, Math.max(8, Math.floor(avail / WINDOW_ROW)))
  let activeIdx = turns.findIndex((t) => t.id === activeTurnId)
  if (activeIdx < 0) activeIdx = 0
  const start = Math.min(Math.max(activeIdx - Math.floor(cap / 2), 0), n - cap)
  return {
    kind: "window",
    row: WINDOW_ROW,
    turns: turns.slice(start, start + cap),
    start,
    end: start + cap,
    total: n,
  }
}

/**
 * Conversation Anchor Rail（对话 Scroll Navigator / Minimap）：
 * 固定在对话区最左侧、垂直居中的一簇短横条，一条横条对应一条用户消息。
 * 当前 Turn 的横条更长更深；Hover 显示问题摘要方形提示；点击滚动到对应 Turn。
 * 无竖线、无展开面板——横条本身就是问题导航。
 */
export function ConversationRail({
  turns,
  activeTurnId,
  onSelect,
}: {
  turns: RailTurn[]
  activeTurnId: string | null
  onSelect: (turnId: string) => void
}) {
  const [vh, setVh] = useState(() => (typeof window === "undefined" ? 800 : window.innerHeight))

  // 窗口尺寸变化时重排横条密度（只在 resize 时触发，无高频计算）
  useEffect(() => {
    const onResize = () => setVh(window.innerHeight)
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [])

  if (!turns.length) return null
  const layout = railLayout(turns, activeTurnId, vh)

  return (
    <div className="absolute left-2 top-1/2 z-20 hidden -translate-y-1/2 md:block sm:left-3">
      <div className="flex flex-col items-center">
        {layout.kind === "window" && layout.start > 0 && (
          <EdgeTick
            title="更早的对话"
            onClick={() => onSelect(turns[layout.start - 1].id)}
          />
        )}
        {layout.turns.map((t) => (
          <RailBar
            key={t.id}
            turnId={t.id}
            preview={t.user.content ?? ""}
            active={activeTurnId === t.id}
            row={layout.row}
            onSelect={onSelect}
          />
        ))}
        {layout.kind === "window" && layout.end < layout.total && (
          <EdgeTick
            title="更晚的对话"
            onClick={() => onSelect(turns[layout.end].id)}
          />
        )}
      </div>
    </div>
  )
}

/** 滑窗边缘提示条：点击翻到前/后一段（跳转到窗口外的第一轮） */
function EdgeTick({ title, onClick }: { title: string; onClick: () => void }) {
  return (
    <Tooltip label={title}>
      <button
        type="button"
        onClick={onClick}
        aria-label={title}
        className="group/tick flex h-[12px] w-[22px] items-center justify-center"
      >
        <span className="h-[2px] w-[10px] rounded-full bg-[rgba(0,0,0,0.10)] transition-all duration-[120ms] ease-out group-hover/tick:w-[16px] group-hover/tick:bg-[rgba(0,0,0,0.30)] dark:bg-[rgba(255,255,255,0.10)] dark:group-hover/tick:bg-[rgba(255,255,255,0.30)]" />
      </button>
    </Tooltip>
  )
}

function RailBar({
  turnId,
  preview,
  active,
  row,
  onSelect,
}: {
  turnId: string
  preview: string
  active: boolean
  row: number
  onSelect: (turnId: string) => void
}) {
  const short = preview.trim().slice(0, 56)
  const label = short.length < preview.trim().length ? `${short}…` : short

  return (
    <button
      type="button"
      onClick={() => onSelect(turnId)}
      aria-label={label ? `跳转到：${label}` : "跳转到对话"}
      style={{ height: row }}
      className="group/bar relative flex w-[22px] items-center justify-center"
    >
      <span
        className={cn(
          "h-[2px] w-[12px] rounded-full transition-all duration-[120ms] ease-out",
          "bg-[rgba(0,0,0,0.18)] group-hover/bar:w-[18px] group-hover/bar:bg-[rgba(0,0,0,0.35)]",
          "dark:bg-[rgba(255,255,255,0.18)] dark:group-hover/bar:bg-[rgba(255,255,255,0.35)]",
          active &&
            "w-[22px] bg-[rgba(0,0,0,0.62)] group-hover/bar:bg-[rgba(0,0,0,0.62)] dark:bg-[rgba(255,255,255,0.62)] dark:group-hover/bar:bg-[rgba(255,255,255,0.62)]"
        )}
      />
      {/* Hover 方形提示：问题摘要（最多 56 字符 + …） */}
      {label && (
        <span className="pointer-events-none absolute left-full top-1/2 z-30 ml-2 hidden w-max max-w-[280px] -translate-y-1/2 rounded-[7px] border border-[var(--border-soft)] bg-workspace px-2.5 py-1.5 text-[12px] leading-[1.4] text-ink shadow-popover group-hover/bar:block">
          {label}
        </span>
      )}
    </button>
  )
}
