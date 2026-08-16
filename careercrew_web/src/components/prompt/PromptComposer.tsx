import { useRef, useEffect, useState, type KeyboardEvent, type PointerEvent, type ReactNode, type RefObject } from "react"
import { ArrowUp, AtSign, Plus, Square, Wrench } from "lucide-react"
import { cn } from "@/lib/utils"
import { Tooltip } from "@/components/ui/tooltip"

/** 输入框可拖拽高度范围（px）：下限 56，上限 400 与 40% 视口高度取小 */
const COMPOSER_MIN_H = 56
const COMPOSER_MAX_H = 400
/** 自动增高（随内容）的上限 */
const AUTOGROW_MAX_H = 240

interface PromptComposerProps {
  value: string
  onChange: (v: string) => void
  onSend: () => void
  placeholder?: string
  disabled?: boolean
  /** 流式生成中：主按钮变为停止按钮 */
  streaming?: boolean
  onStop?: () => void
  /** 输入框上方的附加区域（知识库范围、简历附件等） */
  header?: ReactNode
  /** 底部快捷键提示后的附加说明 */
  hint?: string
  /** 自定义发送按钮文案（如「开始面试」）；不传则显示圆形箭头按钮 */
  sendLabel?: string
  /** 允许空内容发送（面试随机出题场景） */
  allowEmptySend?: boolean
  /** Codex 工具栏（+ / @ / Tools）：主聊天页开启，其余页面不显示 */
  toolbar?: boolean
  /** 附件选择区（AttachmentPicker 等），渲染在工具栏上方；页面接线注入（defer 模式）。 */
  attachments?: ReactNode
  /** @ 引用选择区（MentionPicker 等），渲染在工具栏上方；页面接线注入（defer 模式，T3.4）。 */
  mentions?: ReactNode
  /** 外部引用 textarea（编辑用户消息时聚焦回填） */
  textareaRef?: RefObject<HTMLTextAreaElement | null>
  className?: string
}

/**
 * Prompt Composer（Codex 风格）：
 * 14px 圆角、min-height 56px、极弱边框 + 轻阴影；底部工具栏左 +/@/Tools、右发送。
 * Enter 发送 / Shift + Enter 换行；多行粘贴原样保留。
 */
export function PromptComposer({
  value,
  onChange,
  onSend,
  placeholder = "输入消息…（Enter 发送，Shift + Enter 换行）",
  disabled,
  streaming = false,
  onStop,
  header,
  hint,
  sendLabel,
  allowEmptySend = false,
  toolbar = false,
  attachments,
  mentions,
  textareaRef,
  className,
}: PromptComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null)
  /** 手动拖拽锁定的高度；null = 自动（随内容增高，上限 240px） */
  const [manualHeight, setManualHeight] = useState<number | null>(null)
  const dragRef = useRef({ active: false, startY: 0, startH: COMPOSER_MIN_H, last: COMPOSER_MIN_H })

  // 高度策略：手动拖拽优先；否则空值保持最小高度，有内容时 auto-grow（上限 240）。
  // 注意：空值不清除 manualHeight——否则在空输入框上拖拽拉高会立刻被弹回默认值。
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (manualHeight !== null) {
      el.style.height = `${manualHeight}px`
      return
    }
    if (!el.value) {
      el.style.height = ""
      return
    }
    el.style.height = "auto"
    el.style.height = Math.min(el.scrollHeight, AUTOGROW_MAX_H) + "px"
  }, [value, manualHeight])

  const dragMax = () => Math.min(COMPOSER_MAX_H, Math.round(window.innerHeight * 0.4))

  const handleDragStart = (e: PointerEvent<HTMLDivElement>) => {
    const el = ref.current
    if (!el) return
    e.preventDefault()
    dragRef.current = {
      active: true,
      startY: e.clientY,
      startH: el.offsetHeight,
      last: el.offsetHeight,
    }
    e.currentTarget.setPointerCapture?.(e.pointerId)
  }

  const handleDragMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = dragRef.current
    const el = ref.current
    if (!d.active || !el) return
    // 向上拖 = 拉长（clientY 减小），向下拖 = 缩短，夹在 [min, max] 之间
    const next = Math.min(dragMax(), Math.max(COMPOSER_MIN_H, d.startH + (d.startY - e.clientY)))
    d.last = next
    el.style.height = `${next}px`
  }

  const handleDragEnd = () => {
    const d = dragRef.current
    if (!d.active) return
    d.active = false
    setManualHeight(d.last)
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      if (!disabled && (value.trim() || allowEmptySend)) send()
    }
  }

  /** 发送：恢复自动高度（避免发送后留下手动拖高的大空框） */
  const send = () => {
    setManualHeight(null)
    onSend()
  }

  const canSend = !disabled && (allowEmptySend || Boolean(value.trim()))

  const attachRef = (el: HTMLTextAreaElement | null) => {
    ref.current = el
    if (textareaRef) textareaRef.current = el
  }

  return (
    <div className={cn("mx-auto w-full max-w-[820px]", className)}>
      {header}
      {attachments && <div className="mb-2">{attachments}</div>}
      {mentions && <div className="mb-2">{mentions}</div>}
      <div className="group/composer relative rounded-[14px] border border-input bg-workspace shadow-prompt transition-colors duration-100 focus-within:border-[var(--border-strong)]">
        {/* 拖拽手柄：按住上下拖调整高度（双击恢复自动） */}
        <Tooltip label="拖动调整输入框高度，双击恢复自动">
          <div
            onPointerDown={handleDragStart}
            onPointerMove={handleDragMove}
            onPointerUp={handleDragEnd}
            onPointerCancel={handleDragEnd}
            onDoubleClick={() => setManualHeight(null)}
            className="absolute inset-x-0 top-0 z-10 flex h-[10px] cursor-ns-resize touch-none select-none items-center justify-center"
          >
            <span
              className={cn(
                "h-[3px] w-7 rounded-full bg-[var(--border-strong)] opacity-0 transition-opacity duration-100",
                "group-hover/composer:opacity-100",
                manualHeight !== null && "opacity-60 group-hover/composer:opacity-100"
              )}
            />
          </div>
        </Tooltip>
        <textarea
          ref={attachRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
          className={cn(
            "block min-h-[56px] w-full resize-none border-0 bg-transparent px-3.5 pb-1 pt-3 text-[14px] leading-[1.5] outline-none",
            "placeholder:text-ink-faint disabled:cursor-not-allowed disabled:opacity-60",
            manualHeight !== null && "overflow-y-auto"
          )}
        />
        <div className="flex items-center justify-between gap-2 px-2.5 pb-2 pt-1">
          {toolbar ? (
            <>
              {/* 左：附件 / 提及 / 工具（通用 Agent 提示工具占位） */}
              <div className="flex items-center gap-0.5">
                <ToolbarIconButton title="添加附件" disabled={disabled}>
                  <Plus className="h-[15px] w-[15px]" strokeWidth={1.8} />
                </ToolbarIconButton>
                <ToolbarIconButton title="提及资料" disabled={disabled}>
                  <AtSign className="h-[15px] w-[15px]" strokeWidth={1.8} />
                </ToolbarIconButton>
                <button
                  type="button"
                  disabled={disabled}
                  className="flex h-[26px] items-center gap-1 rounded-[6px] px-1.5 text-[12px] font-medium text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink disabled:pointer-events-none disabled:opacity-50"
                >
                  <Wrench className="h-3.5 w-3.5" strokeWidth={1.8} />
                  Tools
                </button>
              </div>
              {/* 右：发送/停止 */}
              <div className="flex items-center gap-1">
                <ComposerSend
                  streaming={streaming}
                  sendLabel={sendLabel}
                  canSend={canSend}
                  onSend={send}
                  onStop={onStop}
                />
              </div>
            </>
          ) : (
            <>
              <p className="truncate text-[11px] text-ink-faint">
                Enter 发送 · Shift + Enter 换行
                {hint && (
                  <>
                    <span className="mx-1 text-ink-faint opacity-70">·</span>
                    {hint}
                  </>
                )}
              </p>
              <ComposerSend
                streaming={streaming}
                sendLabel={sendLabel}
                canSend={canSend}
                onSend={send}
                onStop={onStop}
              />
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function ToolbarIconButton({
  title,
  disabled,
  children,
}: {
  title: string
  disabled?: boolean
  children: ReactNode
}) {
  return (
    <Tooltip label={title}>
      <button
        type="button"
        disabled={disabled}
        aria-label={title}
        className="flex h-[26px] w-[26px] items-center justify-center rounded-[6px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink disabled:pointer-events-none disabled:opacity-50"
      >
        {children}
      </button>
    </Tooltip>
  )
}

function ComposerSend({
  streaming,
  sendLabel,
  canSend,
  onSend,
  onStop,
}: {
  streaming: boolean
  sendLabel?: string
  canSend: boolean
  onSend: () => void
  onStop?: () => void
}) {
  if (streaming) {
    return (
      <Tooltip label="停止生成">
        <button
          type="button"
          onClick={onStop}
          aria-label="停止生成"
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px] bg-surface-3 text-ink-soft transition-colors duration-100 hover:bg-[var(--active)] hover:text-ink"
        >
          <Square className="h-3 w-3" />
        </button>
      </Tooltip>
    )
  }
  if (sendLabel) {
    return (
      <button
        type="button"
        onClick={onSend}
        disabled={!canSend}
        className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-[7px] bg-button-ink px-2.5 text-[12.5px] font-medium text-button-onink transition-colors duration-100 hover:opacity-90 disabled:pointer-events-none disabled:opacity-40"
      >
        {sendLabel}
        <ArrowUp className="h-3 w-3" />
      </button>
    )
  }
  return (
    <Tooltip label="发送">
      <button
        type="button"
        onClick={onSend}
        disabled={!canSend}
        aria-label="发送"
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px] bg-button-ink text-button-onink transition-colors duration-100 hover:opacity-90 disabled:pointer-events-none disabled:opacity-40"
      >
        <ArrowUp className="h-3.5 w-3.5" />
      </button>
    </Tooltip>
  )
}
