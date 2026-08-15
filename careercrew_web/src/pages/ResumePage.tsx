import { useEffect, useRef, useState, type DragEvent } from "react"
import { Send, Square, Plus, FileText, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { MultilineInput } from "@/components/MultilineInput"
import { InputHint } from "@/components/InputHint"
import { InitIndicator, ThinkingPulse } from "@/components/ThinkingIndicator"
import { MarkdownContent } from "@/components/MarkdownContent"
import { JumpToLatest } from "@/components/JumpToLatest"
import ResumePanel from "@/components/ResumePanel"
import { useChatScroll } from "@/hooks/useChatScroll"
import { useThreadStore } from "@/store/threadStore"
import { IDLE_SESSION, useStreamStore } from "@/store/streamStore"
import { AGENT_META } from "@/types"
import { cn } from "@/lib/utils"
import { pollResumeUpload, type ActiveResume } from "@/lib/resumeUpload"
import { apiFetch } from "@/lib/auth"

let msgId = 0
const nextId = () => `msg-${++msgId}`

const RESUME_ADVISOR = AGENT_META.resume_advisor

interface ChatMsg {
  id: string
  role: "user" | "assistant"
  content: string
  streaming?: boolean
}

export default function ResumePage() {
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState("")
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [panelOpen, setPanelOpen] = useState(false)
  /** 当前会话待使用的简历（展示在输入框上方，可移除）；首轮发送时随请求携带 */
  const [activeResume, setActiveResume] = useState<ActiveResume | null>(null)
  /** 最近上传/选中的简历：首轮发送时随请求携带，之后由后端按线程存储复用 */
  const pendingResumeRef = useRef<{ threadId: string; text: string } | null>(null)
  const currentThreadId = useThreadStore((s) => s.currentThreadByModule.resume)
  // 每会话独立流：切换会话不影响其他会话正在进行的回答
  const stream = useStreamStore((s) => s.sessions[currentThreadId] ?? IDLE_SESSION)
  const startStream = useStreamStore((s) => s.start)
  const stopStream = useStreamStore((s) => s.stop)
  const { scrollRef, showJumpToLatest, jumpToLatest } = useChatScroll([stream.streamingText, messages])
  const initializing = stream.status === "streaming" && stream.streamingText === "" && Object.keys(stream.agentChunks).length === 0

  // 流结束：把最终内容写回最后一条 assistant 气泡
  useEffect(() => {
    if (stream.status !== "done" || !stream.doneContent) return
    setMessages((prev) => prev.map((m, i) =>
      i === prev.length - 1 && (m.streaming ?? false) ? { ...m, content: stream.doneContent, streaming: false } : m,
    ))
  }, [stream.status, stream.doneContent])

  // 流失败：用错误信息填充空气泡
  useEffect(() => {
    if (stream.status !== "error" || !stream.errorMsg) return
    setMessages((prev) => prev.map((m, i) =>
      i === prev.length - 1 ? { ...m, content: stream.errorMsg, streaming: false } : m,
    ))
  }, [stream.status, stream.errorMsg])

  // 当前会话变化（选中历史 / 新建）时加载该 thread 的消息
  useEffect(() => {
    const tid = currentThreadId
    pendingResumeRef.current = null
    setActiveResume(null)
    setMessages([])
    apiFetch(`/api/memory?thread_id=${tid}`)
      .then((r) => r.json())
      .then((entries: Record<string, unknown>[]) => {
        const msgs: ChatMsg[] = []
        for (const entry of entries) {
          const type = String(entry.type || "")
          const content = String(entry.content || "")
          if (type === "user_message" && content) msgs.push({ id: nextId(), role: "user", content })
          else if (type === "agent_response" && content) msgs.push({ id: nextId(), role: "assistant", content })
        }
        // 切回一个仍在流式回答的会话：补一个流式占位气泡
        const live = useStreamStore.getState().sessions[tid]
        setMessages(live && live.status === "streaming"
          ? [...msgs, { id: nextId(), role: "assistant", content: "", streaming: true }]
          : msgs)
        jumpToLatest()
      })
      .catch(() => {})
  }, [currentThreadId, jumpToLatest])

  /** 把一份简历设为当前会话使用的简历（展示在输入框上方，首轮发送时随请求携带）。 */
  const activateResume = (resume: ActiveResume) => {
    pendingResumeRef.current = { threadId: currentThreadId, text: resume.content }
    setActiveResume(resume)
  }

  /** 移除当前会话的简历（不再随首轮发送携带）。 */
  const removeActiveResume = () => {
    pendingResumeRef.current = null
    setActiveResume(null)
  }

  const handleUpload = async (file: File) => {
    if (uploading) return
    setUploading(true)
    try {
      const form = new FormData()
      form.append("file", file)
      const resp = await apiFetch("/api/resume/upload", { method: "POST", body: form })
      const data = await resp.json()
      if (!resp.ok) {
        setMessages((prev) => [...prev, { id: nextId(), role: "user", content: `上传失败：${data.detail || `HTTP ${resp.status}`}` }])
        return
      }
      const job = await pollResumeUpload(data.job_id)
      if (job.status === "error") {
        setMessages((prev) => [...prev, { id: nextId(), role: "user", content: `解析失败：${job.error}` }])
        return
      }
      const r = job.result
      if (r) {
        activateResume({
          resume_id: r.resume_id,
          filename: r.filename,
          doc_type: r.doc_type,
          char_count: r.char_count,
          content: r.content,
        })
      }
    } finally {
      setUploading(false)
    }
  }

  const handleDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleUpload(file)
  }

  const send = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || stream.status === "streaming") return
    const isFirst = messages.length === 0
    const pending = pendingResumeRef.current
    const resumeText = pending && pending.threadId === currentThreadId ? pending.text : ""
    if (pending && pending.threadId === currentThreadId) {
      pendingResumeRef.current = null
      setActiveResume(null)
    }
    setMessages((prev) => [...prev, { id: nextId(), role: "user", content: trimmed }])
    setMessages((prev) => [...prev, { id: nextId(), role: "assistant", content: "", streaming: true }])
    setInput("")
    jumpToLatest()
    if (isFirst) useThreadStore.getState().touchThread("resume", currentThreadId, trimmed)
    await startStream(currentThreadId, "/resume/chat", { question: trimmed, resume_text: resumeText, thread_id: currentThreadId })
  }

  const handleNew = () => {
    pendingResumeRef.current = null
    setActiveResume(null)
    setMessages([])
    setInput("")
    useThreadStore.getState().registerThread("resume")
  }

  const lastIsStreaming = stream.status === "streaming"

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-16 shrink-0 items-center justify-between border-b px-6">
        <div>
          <h1 className="font-display text-xl font-semibold">简历优化</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">上传简历，对话式定制优化 · 按目标 JD 重构</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleNew}>
            <Plus className="mr-1 h-3.5 w-3.5" />新对话
          </Button>
          <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setPanelOpen((v) => !v)}>
            <FileText className="h-4 w-4 text-primary" />
            简历管理
          </Button>
        </div>
      </header>

      <div className="relative flex-1 overflow-hidden">
        <div className="flex h-full flex-col">
          <div className="relative flex-1 overflow-hidden">
            <div
              ref={scrollRef}
              className={cn("h-full overflow-y-auto px-6 py-6", dragOver && "bg-primary/5")}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
            >
              {messages.length === 0 && (
                <EmptyState />
              )}
              <div className="mx-auto max-w-3xl space-y-4">
                {messages.map((msg, i) => (
                  <MessageBubble
                    key={msg.id}
                    msg={msg}
                    isStreaming={lastIsStreaming && i === messages.length - 1 && (msg.streaming ?? false)}
                    streamingText={stream.streamingText}
                    thinking={stream.thinking}
                    initializing={initializing}
                  />
                ))}
              </div>
            </div>
            <JumpToLatest visible={showJumpToLatest} onClick={jumpToLatest} />
          </div>

          <div className="shrink-0 border-t bg-card/50 px-6 py-4">
            {activeResume && (
              <div className="mx-auto mb-2 flex max-w-3xl items-center gap-2">
                <div className="flex items-center gap-2.5 rounded-lg border bg-card py-1.5 pl-3 pr-1.5 shadow-sm">
                  <FileText className="h-4 w-4 shrink-0 text-primary" />
                  <div className="min-w-0">
                    <p className="max-w-[220px] truncate text-xs font-medium">{activeResume.filename}</p>
                    <p className="text-[10px] text-muted-foreground">{activeResume.doc_type} · {activeResume.char_count} 字符</p>
                  </div>
                  <button
                    className="rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    onClick={removeActiveResume}
                    title="移除简历"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            )}
            <div className="mx-auto flex max-w-3xl items-end gap-2">
              <MultilineInput
                value={input}
                onChange={setInput}
                onSend={() => send(input)}
                disabled={stream.status === "streaming"}
                placeholder={activeResume ? "已添加简历，输入目标 JD 或想优化的部分…" : "上传简历，或直接输入简历内容与优化需求…"}
              />
              {stream.status === "streaming" ? (
                <Button variant="destructive" size="icon" onClick={() => stopStream(currentThreadId)} className="h-11 w-11 shrink-0">
                  <Square className="h-4 w-4" />
                </Button>
              ) : (
                <Button size="icon" onClick={() => send(input)} disabled={!input.trim()} className="h-11 w-11 shrink-0">
                  <Send className="h-4 w-4" />
                </Button>
              )}
            </div>
            <InputHint tip="上传简历后，直接描述目标 JD 或想优化的部分" />
          </div>
        </div>

        {/* 右上角简历管理抽屉 */}
        {panelOpen && (
          <aside className="absolute inset-y-0 right-0 z-20 w-[400px] overflow-y-auto border-l bg-background/95 p-4 shadow-2xl backdrop-blur">
            <ResumePanel onClose={() => setPanelOpen(false)} onActive={activateResume} />
          </aside>
        )}
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="mx-auto mt-16 max-w-md text-center">
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
        <FileText className="h-7 w-7 text-primary" />
      </div>
      <h2 className="mt-4 font-display text-2xl font-semibold tracking-tight">上传简历，开始对话式优化</h2>
      <p className="mt-3 text-sm text-muted-foreground">
        点击右上角「简历管理」；<br />
        随后直接在对话里描述目标 JD 或想优化的部分。
      </p>
    </div>
  )
}

function MessageBubble({ msg, isStreaming, streamingText, thinking, initializing }: {
  msg: ChatMsg
  isStreaming: boolean
  streamingText: string
  thinking: boolean
  initializing: boolean
}) {
  const isUser = msg.role === "user"
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
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: RESUME_ADVISOR.color }} />
          <span className="text-xs font-semibold" style={{ color: RESUME_ADVISOR.color }}>{RESUME_ADVISOR.label}</span>
        </div>
        {isStreaming && !content && initializing ? (
          <InitIndicator text="简历顾问正在分析" />
        ) : (
          <>
            <MarkdownContent className={cn(isStreaming && content && !thinking && "typing-cursor")}>
              {content || ""}
            </MarkdownContent>
            {isStreaming && content && thinking && <ThinkingPulse />}
          </>
        )}
      </div>
    </div>
  )
}
