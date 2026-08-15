import { useEffect, useMemo, useRef, useState } from "react"
import { BookOpen, ChevronDown, Plus, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { PromptComposer } from "@/components/prompt/PromptComposer"
import { Tooltip } from "@/components/ui/tooltip"
import { ThinkingPulse } from "@/components/ThinkingIndicator"
import { MarkdownContent } from "@/components/MarkdownContent"
import { WorkspaceHeader } from "@/components/workspace/WorkspaceHeader"
import { EmptyState } from "@/components/workspace/EmptyState"
import KnowledgePanel from "@/components/KnowledgePanel"
import { JumpToLatest } from "@/components/JumpToLatest"
import { AssistantMessage } from "@/components/conversation/AssistantMessage"
import { ConversationRail } from "@/components/conversation/ConversationRail"
import { TurnSection } from "@/components/conversation/TurnSection"
import { ToastBubble } from "@/components/conversation/ToastBubble"
import { groupTurns } from "@/components/conversation/turn"
import { useConversationNavigation } from "@/hooks/useConversationNavigation"
import { useToast } from "@/hooks/useToast"
import { useChatScroll } from "@/hooks/useChatScroll"
import { useThreadStore, type ThreadItem } from "@/store/threadStore"
import { IDLE_SESSION, useStreamStore } from "@/store/streamStore"
import { AGENT_META, KB_CATEGORIES, KB_CATEGORY_LABELS, KB_SCOPE, KB_SCOPE_LABELS, type KnowledgeSource, type MessageFeedback } from "@/types"
import { cn } from "@/lib/utils"
import { apiFetch } from "@/lib/auth"

interface KnowledgeMessage {
  id: string
  role: "user" | "assistant"
  content: string
  streaming?: boolean
  sources?: KnowledgeSource[]
}

let msgId = 0
const nextId = () => `kb-msg-${++msgId}`

/** zustand v5 + React 19：selector 返回新数组会触发 useSyncExternalStore 无限循环，用模块级常量兜底。 */
const EMPTY_THREADS: ThreadItem[] = []

type AuthenticatedImage = { status: "loading" | "ready" | "error"; url?: string }

const imageEndpoint = (path: string) =>
  `/api/knowledge/image?path=${encodeURIComponent(path.replace(/\\/g, "/"))}`

/**
 * <img> 不能携带 Authorization 请求头，所以先通过 apiFetch 取回受保护图片，
 * 再把 Blob URL 交给图片元素。每轮请求产生的 URL 都会在替换或卸载时释放。
 */
function useAuthenticatedImages(paths: readonly (string | undefined)[]) {
  const signature = [...new Set(paths.filter((path): path is string => Boolean(path)))].sort().join("\u0000")

  const [images, setImages] = useState<Record<string, AuthenticatedImage>>({})

  useEffect(() => {
    const uniquePaths = signature ? signature.split("\u0000") : []
    if (uniquePaths.length === 0) {
      setImages({})
      return
    }

    let disposed = false
    const objectUrls: string[] = []
    setImages(Object.fromEntries(uniquePaths.map((path) => [path, { status: "loading" }])) as Record<string, AuthenticatedImage>)

    void Promise.all(uniquePaths.map(async (path) => {
      try {
        const response = await apiFetch(imageEndpoint(path))
        if (!response.ok) throw new Error(`Image request failed: ${response.status}`)
        if (!response.headers.get("Content-Type")?.startsWith("image/")) {
          throw new Error("Image request returned a non-image response")
        }
        const url = URL.createObjectURL(await response.blob())
        objectUrls.push(url)
        return [path, { status: "ready", url }] as const
      } catch {
        return [path, { status: "error" }] as const
      }
    })).then((entries) => {
      if (disposed) return
      setImages(Object.fromEntries(entries))
    })

    return () => {
      disposed = true
      objectUrls.forEach((url) => URL.revokeObjectURL(url))
    }
  }, [signature])

  return images
}

function imagePathsIn(text: string): string[] {
  return [...text.matchAll(/^\[image:\s*(.+?)\]\s*$/gm)].map((match) => match[1])
}

/** 把 rag_query 返回的 [image: 绝对路径] 行转为已鉴权的 Blob 图片。 */
function renderKnowledgeText(text: string, images: Record<string, AuthenticatedImage>): string {
  return text.replace(/^\[image:\s*(.+?)\]\s*$/gm, (_m, rawPath: string) => {
    const image = images[rawPath]
    if (image?.status === "ready" && image.url) return `![知识库图片](${image.url})`
    return image?.status === "error" ? "知识库图片加载失败。" : "知识库图片加载中…"
  })
}

export default function KnowledgePage() {
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<KnowledgeMessage[]>([])
  const [panelOpen, setPanelOpen] = useState(false)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const currentThreadId = useThreadStore((s) => s.currentThreadByModule.knowledge)
  // 检索范围：存于会话元数据（retrieval_scope），切换会话自动恢复，修改即时 PATCH 持久化
  const threads = useThreadStore((s) => s.threadsByModule.knowledge ?? EMPTY_THREADS)
  const setThreadScope = useThreadStore((s) => s.setThreadScope)
  const savedScope = threads.find((t) => t.thread_id === currentThreadId)?.retrieval_scope
  // 范围与分类是两个正交维度：可同时选中（如「公共库 · 面试题」）
  const scope = savedScope?.type ?? "all"
  const category = savedScope?.category_id ?? ""
  const changeCategory = (id: string) => {
    void setThreadScope("knowledge", currentThreadId, { type: scope, category_id: id || null })
  }
  const changeScope = (next: "all" | "public" | "private") => {
    void setThreadScope("knowledge", currentThreadId, { type: next, category_id: category || null })
  }
  // 每会话独立流：切换会话不影响其他会话正在进行的回答
  const stream = useStreamStore((s) => s.sessions[currentThreadId] ?? IDLE_SESSION)
  const startStream = useStreamStore((s) => s.start)
  const stopStream = useStreamStore((s) => s.stop)
  const { scrollRef, showJumpToLatest, jumpToLatest } = useChatScroll([stream.streamingText, messages])
  const initializing = stream.status === "streaming" && stream.streamingText === "" && Object.keys(stream.agentChunks).length === 0
  const meta = AGENT_META.knowledge_advisor

  // ── Turn 分组 + Anchor Rail 导航 ──
  const turns = useMemo(() => groupTurns(messages), [messages])
  const turnIds = useMemo(() => turns.map((t) => t.user.id), [turns])
  const { activeId, selectTurn, highlightId } = useConversationNavigation(turnIds, scrollRef)
  const { toast, showToast } = useToast()
  const composerRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    if (stream.status === "error") {
      // 流出错：移除未填充的空助手占位气泡
      setMessages((prev) =>
        prev.filter((m) => !(m.role === "assistant" && m.streaming && !m.content))
      )
      return
    }
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
    }
  }, [stream.status, stream.doneContent, stream.doneSources])

  // 当前会话变化（选中历史 / 新建）时加载该 thread 的消息
  useEffect(() => {
    const tid = currentThreadId
    setMessages([])
    setPreviewUrl(null)
    apiFetch(`/api/memory?thread_id=${tid}`)
      .then((r) => r.json())
      .then((entries: Record<string, unknown>[]) => {
        const msgs: KnowledgeMessage[] = []
        for (const entry of entries) {
          const type = String(entry.type || "")
          const content = String(entry.content || "")
          const sources = Array.isArray(entry.sources)
            ? (entry.sources as KnowledgeSource[])
            : undefined
          if (type === "user_message" && content) msgs.push({ id: nextId(), role: "user", content })
          else if (type === "agent_response" && content) {
            const msg: KnowledgeMessage = { id: nextId(), role: "assistant", content }
            if (sources) msg.sources = sources
            msgs.push(msg)
          }
        }
        // 切回一个仍在流式回答的会话：补一个流式占位气泡（状态从 store 实时读）
        const live = useStreamStore.getState().sessions[tid]
        setMessages(live && live.status === "streaming"
          ? [...msgs, { id: nextId(), role: "assistant", content: "", streaming: true }]
          : msgs)
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
    await startStream(currentThreadId, "/knowledge/ask", { question, thread_id: currentThreadId, category, scope })
  }

  /** 重新生成：移除该回答后重发同一问题（不新建用户消息） */
  const handleRegenerate = async (turnId: string) => {
    if (stream.status === "streaming") return
    const turn = groupTurns(messages).find((t) => t.id === turnId)
    if (!turn?.assistant || !turn.user.content) return
    const removedId = turn.assistant.id
    setMessages((prev) => prev.filter((m) => m.id !== removedId))
    setMessages((prev) => [...prev, { id: nextId(), role: "assistant", content: "", streaming: true }])
    jumpToLatest()
    await startStream(currentThreadId, "/knowledge/ask", {
      question: turn.user.content,
      thread_id: currentThreadId,
      category,
      scope,
    })
  }

  const handleEdit = (text: string) => {
    setInput(text)
    requestAnimationFrame(() => composerRef.current?.focus())
  }

  const handleNew = () => {
    setMessages([])
    setPreviewUrl(null)
    useThreadStore.getState().registerThread("knowledge")
  }

  const lastIsStreaming = stream.status === "streaming"

  return (
    <div className="flex h-full flex-col">
      <WorkspaceHeader
        title="知识库问答"
        subtitle="基于知识库文档检索回答，点击来源可查看原文"
        actions={
          <>
            <Button variant="outline" size="sm" onClick={handleNew}>
              <Plus className="mr-1 h-3.5 w-3.5" strokeWidth={1.7} />新对话
            </Button>
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setPanelOpen((v) => !v)}>
              <BookOpen className="h-3.5 w-3.5 text-primary" strokeWidth={1.7} />
              知识库管理
            </Button>
          </>
        }
      />

      <div className="relative flex-1 overflow-hidden">
        <div ref={scrollRef} className="h-full overflow-y-auto">
          <div className="relative mx-auto w-full max-w-[928px] px-4 pb-[200px] pt-7 sm:px-6 md:pl-12">
            {messages.length === 0 ? (
              <EmptyState
                title="向知识库提问"
                description={
                  <>
                    输入问题后，自动检索知识库并生成回答；
                    <br />
                    回答会标注数据来源，点击即可查看对应片段。
                  </>
                }
                accent={
                  <span className="flex h-9 w-9 items-center justify-center rounded-[9px] bg-surface-2">
                    <BookOpen className="h-4 w-4" style={{ color: meta.color }} strokeWidth={1.7} />
                  </span>
                }
              />
            ) : (
              <div className="flex flex-col gap-10">
                {turns.map((turn, i) => {
                  const isLast = i === turns.length - 1
                  const asst = turn.assistant
                  const asstStreaming = Boolean(asst?.streaming) && lastIsStreaming && isLast
                  return (
                    <TurnSection
                      key={turn.id}
                      turnId={turn.id}
                      userContent={turn.user.content}
                      isUser={turn.user.role === "user"}
                      highlighted={highlightId === turn.id}
                      onEdit={handleEdit}
                    >
                      {asst && (
                        <KnowledgeAssistant
                          msg={asst}
                          isStreaming={asstStreaming}
                          streamingText={stream.streamingText}
                          thinking={stream.thinking}
                          initializing={initializing}
                          onPreview={setPreviewUrl}
                          onRegenerate={
                            isLast && !asstStreaming && Boolean(asst.content) && Boolean(turn.user.content)
                              ? () => handleRegenerate(turn.id)
                              : undefined
                          }
                          onFeedback={() => showToast("感谢你的反馈")}
                        />
                      )}
                    </TurnSection>
                  )
                })}

                {stream.errorMsg && (
                  <Card className="border-destructive/40">
                    <CardContent className="p-4 text-[13px] text-destructive">{stream.errorMsg}</CardContent>
                  </Card>
                )}
              </div>
            )}
          </div>
        </div>

        <ConversationRail turns={turns} activeTurnId={activeId} onSelect={selectTurn} />
        <div className="composer-fade pointer-events-none absolute inset-x-0 bottom-0 z-10 h-[150px]" />
        <JumpToLatest visible={showJumpToLatest} onClick={jumpToLatest} className="bottom-[110px]" />
        <div className="absolute inset-x-0 bottom-0 z-20 flex justify-center px-3 pb-3 sm:px-6 sm:pb-4">
          <PromptComposer
            value={input}
            onChange={setInput}
            onSend={handleAsk}
            disabled={lastIsStreaming}
            streaming={lastIsStreaming}
            onStop={() => stopStream(currentThreadId)}
            placeholder="输入问题，将自动检索知识库后回答"
            hint="知识库图片会自动内嵌显示"
            textareaRef={composerRef}
            className="w-full"
            header={
              <div className="mb-2 flex flex-wrap items-center gap-1.5">
                <span className="mr-0.5 text-[11px] font-medium text-ink-faint">范围</span>
                {KB_SCOPE.map((s) => (
                  <Chip key={s.id} active={scope === s.id} onClick={() => changeScope(s.id)}>
                    {s.label}
                  </Chip>
                ))}
                <span aria-hidden className="mx-1 h-3 w-px bg-[var(--border-normal)]" />
                <span className="mr-0.5 text-[11px] font-medium text-ink-faint">分类</span>
                {KB_CATEGORIES.map((c) => (
                  <Chip key={c.id || "all"} active={category === c.id} onClick={() => changeCategory(c.id)}>
                    {c.label}
                  </Chip>
                ))}
                <span className="ml-auto text-[11px] text-ink-faint">
                  当前：{KB_SCOPE_LABELS[scope]} · {KB_CATEGORY_LABELS[category] ?? "全部分类"}
                </span>
              </div>
            }
          />
        </div>
        <ToastBubble message={toast} />

        {/* 右上角知识库管理抽屉 */}
        {panelOpen && (
          <aside className="absolute inset-y-0 right-0 z-20 w-[400px] overflow-y-auto border-l border-[var(--border-soft)] bg-workspace p-4">
            <KnowledgePanel onClose={() => setPanelOpen(false)} />
          </aside>
        )}

        {previewUrl && <Lightbox src={previewUrl} onClose={() => setPreviewUrl(null)} />}
      </div>
    </div>
  )
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: string }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition-colors duration-100",
        active
          ? "border-transparent bg-button-ink text-button-onink"
          : "border-[var(--border-soft)] bg-transparent text-ink-soft hover:bg-[var(--hover)] hover:text-ink"
      )}
    >
      {children}
    </button>
  )
}

function KnowledgeAssistant({ msg, isStreaming, streamingText, thinking, initializing, onPreview, onRegenerate, onFeedback }: {
  msg: KnowledgeMessage
  isStreaming: boolean
  streamingText: string
  thinking: boolean
  initializing: boolean
  onPreview: (url: string) => void
  onRegenerate?: () => void
  onFeedback?: (fb: MessageFeedback) => void
}) {
  const meta = AGENT_META.knowledge_advisor
  const content = isStreaming ? streamingText : msg.content
  const images = useAuthenticatedImages(isStreaming ? imagePathsIn(streamingText) : imagePathsIn(msg.content))
  const rendered = renderKnowledgeText(content, images)

  return (
    <AssistantMessage
      messageId={msg.id}
      content={content}
      label={meta.label}
      color={meta.color}
      streaming={isStreaming}
      thinking={thinking}
      initializing={isStreaming && !content && initializing}
      initText="正在检索知识库"
      workingText="正在检索知识库…"
      contentNode={
        <>
          <MarkdownContent className={cn(isStreaming && content && !thinking && "typing-cursor")}>
            {rendered}
          </MarkdownContent>
          {isStreaming && content && thinking && <ThinkingPulse />}
        </>
      }
      onRegenerate={onRegenerate}
      onFeedback={onFeedback}
    >
      {!isStreaming && msg.sources && msg.sources.length > 0 && (
        <SourceList sources={msg.sources} onPreview={onPreview} />
      )}
    </AssistantMessage>
  )
}

function SourceList({ sources, onPreview }: { sources: KnowledgeSource[]; onPreview: (url: string) => void }) {
  const [open, setOpen] = useState<Set<number>>(new Set())
  const [failedImgs, setFailedImgs] = useState<Set<string>>(new Set())
  const images = useAuthenticatedImages(sources.map((source) => source.image_path))

  const toggle = (i: number) => {
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  }

  return (
    <div className="mt-3 space-y-1.5 border-t border-[var(--border-soft)] pt-2.5">
      <p className="text-[11px] font-medium text-ink-faint">
        数据来源（{sources.length}）· 点击查看原文
      </p>
      {sources.map((s, i) => {
        const expanded = open.has(i)
        const name = s.doc || s.source.split(/[\\/]/).pop() || `来源 ${i + 1}`
        // 原始相关度百分比（0-1 -> 0-100%），不做相对归一化，避免低分片段显示成 100%
        const pct = Math.round(s.score * 100)
        const imgPath = s.image_path
        const image = imgPath ? images[imgPath] : undefined
        return (
          <div key={`${s.doc}-${i}`} className="overflow-hidden rounded-[8px] border border-[var(--border-soft)] bg-surface-2">
            <button
              onClick={() => toggle(i)}
              className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left transition-colors duration-100 hover:bg-[var(--hover)]"
            >
              <span className="text-[10.5px] font-medium text-ink-faint">[{i + 1}]</span>
              <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-ink">{name}</span>
              {s.category && (
                <span className="shrink-0 rounded-[5px] bg-surface-3 px-1.5 py-0.5 text-[10px] text-ink-soft">
                  {KB_CATEGORY_LABELS[s.category] ?? s.category}
                </span>
              )}
              {s.used_image ? (
                <span className="shrink-0 rounded-[5px] bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                  已读图
                </span>
              ) : (
                <span className="shrink-0 text-[10px] text-ink-faint">相关度 {pct}%</span>
              )}
              <ChevronDown className={cn("h-3 w-3 shrink-0 text-ink-faint transition-transform duration-100", expanded && "rotate-180")} />
            </button>
            {expanded && (
              <div className="border-t border-[var(--border-soft)] bg-workspace px-3 py-2">
                {imgPath && (
                  failedImgs.has(imgPath) || image?.status === "error" ? (
                    <p className="mb-1.5 truncate text-[10.5px] text-ink-faint">
                      图片：{imgPath.replace(/\\/g, "/")}
                    </p>
                  ) : image?.status !== "ready" || !image.url ? (
                    <p className="mb-1.5 text-[10.5px] text-ink-faint">图片加载中…</p>
                  ) : (
                    <Tooltip label="点击查看大图（滚轮缩放）">
                      <button
                        onClick={() => onPreview(image.url!)}
                        className="mb-2 block w-full"
                      >
                        <img
                          src={image.url}
                          alt={name}
                          className="max-h-44 w-full rounded-[7px] bg-surface-2 object-contain transition-opacity duration-100 hover:opacity-90"
                          onError={() => setFailedImgs((prev) => new Set(prev).add(imgPath))}
                        />
                      </button>
                    </Tooltip>
                  )
                )}
                <p className="whitespace-pre-wrap text-[12px] leading-relaxed text-ink-soft">{s.text}</p>
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
      <Tooltip label="关闭">
        <button
          className="absolute right-4 top-4 rounded-full bg-white/10 p-2 text-white transition-colors duration-100 hover:bg-white/20"
          onClick={onClose}
          aria-label="关闭"
        >
          <X className="h-5 w-5" />
        </button>
      </Tooltip>
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
          className="rounded-[5px] bg-white/15 px-2 py-0.5 transition-colors duration-100 hover:bg-white/25"
          onClick={resetZoom}
        >
          重置
        </button>
      </div>
    </div>
  )
}
