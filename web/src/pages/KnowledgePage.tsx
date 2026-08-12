import { useEffect, useRef, useState } from "react"
import { BookOpen, ChevronDown, CornerDownLeft, Plus, Send, Square, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { MultilineInput } from "@/components/MultilineInput"
import { InitIndicator, ThinkingPulse } from "@/components/ThinkingIndicator"
import { MarkdownContent } from "@/components/MarkdownContent"
import KnowledgePanel from "@/components/KnowledgePanel"
import { JumpToLatest } from "@/components/JumpToLatest"
import { useChatStream } from "@/hooks/useChatStream"
import { useChatScroll } from "@/hooks/useChatScroll"
import { useThreadStore } from "@/store/threadStore"
import { AGENT_META, type KnowledgeSource } from "@/types"
import { cn } from "@/lib/utils"

interface KnowledgeMessage {
  id: string
  role: "user" | "assistant"
  content: string
  streaming?: boolean
  sources?: KnowledgeSource[]
}

let msgId = 0
const nextId = () => `kb-msg-${++msgId}`

/** 知识库图片 -> 后端安全代理 URL（浏览器无法直接加载本地绝对路径）。 */
function imageUrl(path: string): string {
  return path ? `/api/knowledge/image?path=${encodeURIComponent(path.replace(/\\/g, "/"))}` : ""
}

/** 把 rag_query 返回的 [image: 绝对路径] 行转为 markdown 图片语法（仅本页）。 */
function renderKnowledgeText(text: string): string {
  return text.replace(
    /^\[image:\s*(.+?)\]\s*$/gm,
    (_m, path: string) => `![知识库图片](${imageUrl(String(path))})`
  )
}

export default function KnowledgePage() {
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<KnowledgeMessage[]>([])
  const [panelOpen, setPanelOpen] = useState(false)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const stream = useChatStream()
  const { scrollRef, showJumpToLatest, jumpToLatest } = useChatScroll([stream.streamingText, messages])
  const currentThreadId = useThreadStore((s) => s.currentThreadByModule.knowledge)
  const meta = AGENT_META.knowledge_advisor

  useEffect(() => {
    if (stream.status === "done" && stream.doneContent) {
      setMessages((prev) => {
        const msgs = [...prev]
        for (let i = msgs.length - 1; i >= 0; i--) {
          if (msgs[i].role === "assistant" && msgs[i].streaming) {
            msgs[i] = { ...msgs[i], content: stream.doneContent, sources: stream.doneSources, streaming: false }
            break
          }
        }
        return msgs
      })
      useThreadStore.getState().bumpNonce()
    }
  }, [stream.status, stream.doneContent, stream.doneSources])

  // 当前会话变化（选中历史 / 新建）时加载该 thread 的消息
  useEffect(() => {
    const tid = currentThreadId
    stream.reset()
    setMessages([])
    setPreviewUrl(null)
    fetch(`/api/memory?thread_id=${tid}`)
      .then((r) => r.json())
      .then((entries: Record<string, unknown>[]) => {
        const msgs: KnowledgeMessage[] = []
        for (const entry of entries) {
          const type = String(entry.type || "")
          const content = String(entry.content || "")
          if (type === "user_message" && content) msgs.push({ id: nextId(), role: "user", content })
          else if (type === "agent_response" && content) msgs.push({ id: nextId(), role: "assistant", content })
        }
        setMessages(msgs)
        jumpToLatest()
      })
      .catch(() => {})
  }, [currentThreadId, jumpToLatest])

  const handleAsk = async () => {
    const question = input
    if (!question.trim() || stream.status === "streaming") return
    const isFirst = messages.length === 0
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", content: question },
      { id: nextId(), role: "assistant", content: "", streaming: true },
    ])
    setInput("")
    jumpToLatest()
    if (isFirst) useThreadStore.getState().touchThread("knowledge", currentThreadId, question)
    await stream.start("/knowledge/ask", { question, thread_id: currentThreadId })
  }

  const handleNew = () => {
    if (stream.status === "streaming") stream.stop()
    stream.reset()
    setMessages([])
    setPreviewUrl(null)
    useThreadStore.getState().registerThread("knowledge")
  }

  const lastIsStreaming = stream.status === "streaming"

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-16 shrink-0 items-center justify-between border-b px-6">
        <div>
          <h1 className="font-display text-xl font-semibold">知识库问答</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">基于知识库文档检索回答，点击来源可查看原文</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleNew}>
            <Plus className="mr-1 h-3.5 w-3.5" />新对话
          </Button>
          <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setPanelOpen((v) => !v)}>
            <BookOpen className="h-4 w-4 text-primary" />
            知识库管理
          </Button>
        </div>
      </header>

      <div className="relative flex-1 overflow-hidden">
        <div className="flex h-full flex-col">
          <div className="relative flex-1 overflow-hidden">
            <div ref={scrollRef} className="h-full overflow-y-auto px-6 py-6">
              {messages.length === 0 && (
                <div className="mx-auto mt-16 max-w-md text-center">
                  <div className="mb-6 flex justify-center">
                    <BookOpen className="h-10 w-10" style={{ color: meta.color }} />
                  </div>
                  <h2 className="font-display text-2xl font-semibold tracking-tight">向知识库提问</h2>
                  <p className="mt-3 text-sm text-muted-foreground">
                    输入问题后，自动检索知识库并生成回答；
                    <br />
                    回答会标注数据来源，点击即可查看对应片段。
                  </p>
                </div>
              )}
              <div className="mx-auto max-w-3xl space-y-4">
                {messages.map((msg) => (
                  <MessageBubble
                    key={msg.id}
                    msg={msg}
                    isStreaming={lastIsStreaming && msg.role === "assistant" && (msg.streaming ?? false)}
                    streamingText={stream.streamingText}
                    thinking={stream.thinking}
                    initializing={stream.initializing}
                    onPreview={setPreviewUrl}
                  />
                ))}

                {stream.errorMsg && (
                  <Card className="border-destructive">
                    <CardContent className="p-4 text-sm text-destructive">{stream.errorMsg}</CardContent>
                  </Card>
                )}
              </div>
            </div>
            <JumpToLatest visible={showJumpToLatest} onClick={jumpToLatest} />
          </div>

          <div className="shrink-0 border-t bg-card/50 px-6 py-4">
            <div className="mx-auto flex max-w-3xl items-end gap-2">
              <MultilineInput
                value={input}
                onChange={setInput}
                onSend={handleAsk}
                disabled={stream.status === "streaming"}
                placeholder="输入问题，将自动检索知识库后回答"
              />
              {stream.status === "streaming" ? (
                <Button variant="destructive" size="icon" onClick={stream.stop} className="h-11 w-11 shrink-0">
                  <Square className="h-4 w-4" />
                </Button>
              ) : (
                <Button size="icon" onClick={handleAsk} disabled={!input.trim()} className="h-11 w-11 shrink-0">
                  <Send className="h-4 w-4" />
                </Button>
              )}
            </div>
            <p className="mx-auto mt-2 flex max-w-3xl items-center gap-1 text-[11px] text-muted-foreground">
              <CornerDownLeft className="h-3 w-3" /> 发送
              <span className="mx-1">·</span>
              Shift + Enter 换行 · 知识库图片会自动内嵌显示
            </p>
          </div>
        </div>

        {/* 右上角知识库管理抽屉 */}
        {panelOpen && (
          <aside className="absolute inset-y-0 right-0 z-20 w-[400px] overflow-y-auto border-l bg-background/95 p-4 shadow-2xl backdrop-blur">
            <KnowledgePanel onClose={() => setPanelOpen(false)} />
          </aside>
        )}

        {previewUrl && <Lightbox src={previewUrl} onClose={() => setPreviewUrl(null)} />}
      </div>
    </div>
  )
}

function MessageBubble({ msg, isStreaming, streamingText, thinking, initializing, onPreview }: {
  msg: KnowledgeMessage
  isStreaming: boolean
  streamingText: string
  thinking: boolean
  initializing: boolean
  onPreview: (url: string) => void
}) {
  const isUser = msg.role === "user"
  const meta = AGENT_META.knowledge_advisor
  const content = isStreaming ? streamingText : msg.content

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-lg rounded-br-sm bg-primary px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap text-primary-foreground">
          {content}
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start">
      <div className="stream-fade-in max-w-[85%] rounded-lg rounded-bl-sm border bg-card px-4 py-3">
        <div className="mb-1.5 flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: meta.color }} />
          <span className="text-xs font-semibold" style={{ color: meta.color }}>{meta.label}</span>
        </div>
        {isStreaming && !content && initializing ? (
          <InitIndicator text="正在检索知识库" />
        ) : (
          <>
            <MarkdownContent className={cn(isStreaming && content && !thinking && "typing-cursor")}>
              {renderKnowledgeText(content || "")}
            </MarkdownContent>
            {isStreaming && content && thinking && <ThinkingPulse />}
            {!isStreaming && msg.sources && msg.sources.length > 0 && (
              <SourceList sources={msg.sources} onPreview={onPreview} />
            )}
          </>
        )}
      </div>
    </div>
  )
}

function SourceList({ sources, onPreview }: { sources: KnowledgeSource[]; onPreview: (url: string) => void }) {
  const [open, setOpen] = useState<Set<number>>(new Set())
  const [failedImgs, setFailedImgs] = useState<Set<number>>(new Set())

  const toggle = (i: number) => {
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  }

  return (
    <div className="mt-3 space-y-1.5 border-t pt-2">
      <p className="text-[11px] font-medium text-muted-foreground">
        数据来源（{sources.length}）· 点击查看原文
      </p>
      {sources.map((s, i) => {
        const expanded = open.has(i)
        const name = s.doc || s.source.split(/[\\/]/).pop() || `来源 ${i + 1}`
        // 原始相关度百分比（0-1 -> 0-100%），不做相对归一化，避免低分片段显示成 100%
        const pct = Math.round(s.score * 100)
        const imgPath = s.image_path
        return (
          <div key={`${s.doc}-${i}`} className="overflow-hidden rounded-md border bg-muted/30">
            <button
              onClick={() => toggle(i)}
              className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left transition-colors hover:bg-muted"
            >
              <span className="text-[10px] font-semibold text-primary">[{i + 1}]</span>
              <span className="min-w-0 flex-1 truncate text-xs font-medium">{name}</span>
              {s.used_image ? (
                <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                  已读图
                </span>
              ) : (
                <span className="shrink-0 text-[10px] text-muted-foreground">相关度 {pct}%</span>
              )}
              <ChevronDown className={cn("h-3 w-3 shrink-0 text-muted-foreground transition-transform", expanded && "rotate-180")} />
            </button>
            {expanded && (
              <div className="border-t bg-card px-3 py-2">
                {imgPath && (
                  failedImgs.has(i) ? (
                    <p className="mb-1.5 truncate text-[10px] text-muted-foreground">
                      图片：{imgPath.replace(/\\/g, "/")}
                    </p>
                  ) : (
                    <button
                      onClick={() => onPreview(imageUrl(imgPath))}
                      className="mb-2 block w-full"
                      title="点击查看大图（滚轮缩放）"
                    >
                      <img
                        src={imageUrl(imgPath)}
                        alt={name}
                        className="max-h-44 w-full bg-muted object-contain transition-opacity hover:opacity-90"
                        onError={() => setFailedImgs((prev) => new Set(prev).add(i))}
                      />
                    </button>
                  )
                )}
                <p className="whitespace-pre-wrap text-xs leading-relaxed text-foreground/90">{s.text}</p>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function Lightbox({ src, onClose }: { src: string; onClose: () => void }) {
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 })
  const imgRef = useRef<HTMLImageElement>(null)
  const dragRef = useRef<{
    startX: number
    startY: number
    origX: number
    origY: number
    lastX: number
    lastY: number
  } | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    // 锁定 body 滚动：避免底层页面滚动条透过半透明遮罩显示成白线
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      window.removeEventListener("keydown", onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [onClose])

  // 滚轮缩放：用原生非 passive 监听，阻止背景滚动
  useEffect(() => {
    const el = imgRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      // 归一化 delta：鼠标一格≈100px（deltaMode 1=行、2=页）
      let dy = e.deltaY
      if (e.deltaMode === 1) dy *= 16
      else if (e.deltaMode === 2) dy *= 100
      // 单次事件最多变化 0.5x~2x，避免"滚一下就最大"
      const ratio = Math.min(2, Math.max(0.5, Math.exp(-dy * 0.0015)))
      setView((v) => {
        const next = Math.min(5, Math.max(1, v.scale * ratio))
        const r = next / v.scale
        const max = (next - 1) * 500
        return {
          scale: next,
          x: Math.min(max, Math.max(-max, v.x * r)),
          y: Math.min(max, Math.max(-max, v.y * r)),
        }
      })
    }
    el.addEventListener("wheel", onWheel, { passive: false })
    return () => el.removeEventListener("wheel", onWheel)
  }, [])

  const resetZoom = () => setView({ scale: 1, x: 0, y: 0 })
  const maxOffset = (view.scale - 1) * 500
  const clampAxis = (v: number, max: number) => Math.min(max, Math.max(-max, v))

  /** 拖拽期间直接改 DOM transform（不触发 React 重渲染，避免滞后）。 */
  const applyTransform = (x: number, y: number, s: number) => {
    const el = imgRef.current
    if (el) el.style.transform = `translate3d(${x}px, ${y}px, 0) scale(${s})`
  }

  const onMouseDown = (e: React.MouseEvent) => {
    if (view.scale <= 1) return
    e.preventDefault()
    dragRef.current = {
      startX: e.clientX, startY: e.clientY,
      origX: view.x, origY: view.y,
      lastX: view.x, lastY: view.y,
    }
  }

  const onMouseMove = (e: React.MouseEvent) => {
    const d = dragRef.current
    if (!d) return
    d.lastX = clampAxis(d.origX + (e.clientX - d.startX), maxOffset)
    d.lastY = clampAxis(d.origY + (e.clientY - d.startY), maxOffset)
    applyTransform(d.lastX, d.lastY, view.scale)
  }

  const endDrag = () => {
    const d = dragRef.current
    if (d) {
      // 松手时把最终位置同步回 state（只重渲染一次）
      setView((v) => ({ ...v, x: d.lastX, y: d.lastY }))
    }
    dragRef.current = null
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-hidden bg-black/85 p-6"
      onClick={onClose}
    >
      <button
        className="absolute right-4 top-4 rounded-full bg-white/10 p-2 text-white transition-colors hover:bg-white/20"
        onClick={onClose}
        title="关闭"
      >
        <X className="h-5 w-5" />
      </button>
      <img
        ref={imgRef}
        src={src}
        alt="知识库图片大图"
        draggable={false}
        onDragStart={(e) => e.preventDefault()}
        className={cn(
          "max-h-[90vh] max-w-[90vw] object-contain select-none will-change-transform",
          view.scale > 1 ? "cursor-grab active:cursor-grabbing" : "cursor-zoom-in"
        )}
        style={{ transform: `translate3d(${view.x}px, ${view.y}px, 0) scale(${view.scale})` }}
        onClick={(e) => e.stopPropagation()}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={endDrag}
        onMouseLeave={endDrag}
      />
      <div
        className="absolute bottom-5 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-full bg-white/10 px-3 py-1.5 text-xs text-white"
        onClick={(e) => e.stopPropagation()}
      >
        <span className="tabular-nums">缩放 {Math.round(view.scale * 100)}%</span>
        {view.scale > 1 && <span className="text-white/60">拖拽可移动</span>}
        <button
          className="rounded bg-white/15 px-2 py-0.5 transition-colors hover:bg-white/25"
          onClick={resetZoom}
          title="重置缩放"
        >
          重置
        </button>
      </div>
    </div>
  )
}
