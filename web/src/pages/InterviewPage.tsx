import { useEffect, useRef, useState } from "react"
import { Send, Square, CornerDownLeft, Plus, BookOpen, Check } from "lucide-react"
import { Button } from "@/components/ui/button"
import { MultilineInput } from "@/components/MultilineInput"
import { InitIndicator, ThinkingPulse } from "@/components/ThinkingIndicator"
import { MarkdownContent } from "@/components/MarkdownContent"
import { useChatStream } from "@/hooks/useChatStream"
import { useChatScroll } from "@/hooks/useChatScroll"
import { JumpToLatest } from "@/components/JumpToLatest"
import { useThreadStore } from "@/store/threadStore"
import { cn } from "@/lib/utils"
import type { InterviewQA } from "@/types"

const INTERVIEWER = { label: "面试官", color: "#BE185D" }

let msgId = 0
const nextId = () => `msg-${++msgId}`

interface ChatMsg {
  id: string
  role: "user" | "assistant"
  content: string
  streaming?: boolean
  score?: number
  feedback?: string
}

export default function InterviewPage() {
  const [topic, setTopic] = useState("")
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState("")
  const [qaList, setQaList] = useState<InterviewQA[]>([])
  const stream = useChatStream()
  const { scrollRef, showJumpToLatest, jumpToLatest } = useChatScroll([stream.streamingText, messages])
  const currentThreadId = useThreadStore((s) => s.currentThreadByModule.interview)
  /** 当前作答对应的题目（用户回答前最近一条面试官消息），done 评分后入 qaList */
  const pendingRef = useRef<{ q: string; a: string } | null>(null)

  // 流结束：把最终内容写回最后一条 assistant 气泡；若带评分则计入 qaList
  useEffect(() => {
    if (stream.status !== "done" || !stream.doneContent) return
    const pending = pendingRef.current
    pendingRef.current = null
    const patch: Partial<ChatMsg> = { content: stream.doneContent, streaming: false }
    if (stream.doneScore !== undefined && pending) {
      patch.score = stream.doneScore
      patch.feedback = stream.doneFeedback
      setQaList((prev) => [...prev, {
        question: pending.q,
        answer: pending.a,
        score: stream.doneScore,
        feedback: stream.doneFeedback,
      }])
    }
    useThreadStore.getState().bumpNonce()
    setMessages((prev) => prev.map((m, i) => (i === prev.length - 1 ? { ...m, ...patch } : m)))
  }, [stream.status, stream.doneContent, stream.doneScore, stream.doneFeedback])

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
    stream.reset()
    pendingRef.current = null
    setMessages([])
    setQaList([])
    setTopic("")
    fetch(`/api/memory?thread_id=${tid}`)
      .then((r) => r.json())
      .then((entries: Record<string, unknown>[]) => {
        const msgs: ChatMsg[] = []
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

  const send = async (text: string, topicOverride?: string) => {
    const trimmed = text.trim()
    if (!trimmed || stream.status === "streaming") return
    const isFirst = messages.length === 0
    const prev = messages[messages.length - 1]
    pendingRef.current = prev?.role === "assistant" && prev.content
      ? { q: prev.content, a: trimmed }
      : null
    setMessages((prev) => [...prev, { id: nextId(), role: "user", content: trimmed }])
    setMessages((prev) => [...prev, { id: nextId(), role: "assistant", content: "", streaming: true }])
    setInput("")
    jumpToLatest()
    if (isFirst) useThreadStore.getState().touchThread("interview", currentThreadId, topicOverride || text)
    const history = [...messages, { role: "user", content: trimmed }].map((m) => ({
      role: m.role,
      content: m.content,
    }))
    await stream.start("/interview/chat", { topic: topicOverride ?? topic, messages: history, thread_id: currentThreadId })
  }

  const startWithTopic = (t: string) => {
    const topicText = t.trim() || "随机出题"
    setTopic(topicText)
    send(topicText, topicText)
  }

  const handleEnd = () => {
    if (stream.status === "streaming") return
    send("结束面试，请给出整体总结与改进建议")
  }

  const handleRecord = async () => {
    if (qaList.length === 0) return
    await fetch("/api/interview/record", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entries: qaList.map((qa) => ({ q: qa.question, a: qa.answer, score: qa.score })) }),
    })
    setQaList([])
  }

  const handleNew = () => {
    stream.reset()
    pendingRef.current = null
    setMessages([])
    setQaList([])
    setTopic("")
    setInput("")
    useThreadStore.getState().registerThread("interview")
  }

  const lastIsStreaming = stream.status === "streaming"

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-16 shrink-0 items-center justify-between border-b px-6">
        <div>
          <h1 className="font-display text-xl font-semibold">面试练习</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">对话式模拟面试 · 出题 → 作答 → 评分 → 追问</p>
        </div>
        <div className="flex items-center gap-2">
          {messages.length > 0 && (
            <Button variant="outline" size="sm" onClick={handleEnd} disabled={lastIsStreaming}>
              结束面试
            </Button>
          )}
          {qaList.length > 0 && (
            <Button variant="outline" size="sm" onClick={handleRecord}>
              <Check className="mr-1 h-3.5 w-3.5" />保存 {qaList.length} 条到记忆
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={handleNew}>
            <Plus className="mr-1 h-3.5 w-3.5" />新面试
          </Button>
        </div>
      </header>

      <div className="relative flex-1 overflow-hidden">
        <div ref={scrollRef} className="h-full overflow-y-auto px-6 py-6">
          {messages.length === 0 && (
            <EmptyState
              value={input}
              onChange={setInput}
              onStart={startWithTopic}
            />
          )}
          <div className="mx-auto max-w-3xl space-y-4">
            {messages.map((msg, i) => (
              <MessageBubble
                key={msg.id}
                msg={msg}
                isStreaming={lastIsStreaming && i === messages.length - 1 && (msg.streaming ?? false)}
                streamingText={stream.streamingText}
                thinking={stream.thinking}
                initializing={stream.initializing}
              />
            ))}
          </div>
        </div>
        <JumpToLatest visible={showJumpToLatest} onClick={jumpToLatest} />
      </div>

      {messages.length > 0 && (
        <div className="shrink-0 border-t bg-card/50 px-6 py-4">
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <MultilineInput
              value={input}
              onChange={setInput}
              onSend={() => send(input)}
              disabled={lastIsStreaming}
              placeholder="作答，或输入「结束面试」获取总结…"
            />
            {lastIsStreaming ? (
              <Button variant="destructive" size="icon" onClick={stream.stop} className="h-11 w-11 shrink-0">
                <Square className="h-4 w-4" />
              </Button>
            ) : (
              <Button size="icon" onClick={() => send(input)} disabled={!input.trim()} className="h-11 w-11 shrink-0">
                <Send className="h-4 w-4" />
              </Button>
            )}
          </div>
          <p className="mx-auto mt-2 flex max-w-3xl items-center gap-1 text-[11px] text-muted-foreground">
            <CornerDownLeft className="h-3 w-3" /> 发送
            <span className="mx-1">·</span>
            Shift + Enter 换行 · 面试官一轮一问，回答后自动评分并追问
          </p>
        </div>
      )}
    </div>
  )
}

function EmptyState({ value, onChange, onStart }: {
  value: string
  onChange: (v: string) => void
  onStart: (topic: string) => void
}) {
  return (
    <div className="mx-auto mt-14 max-w-md text-center">
      <div className="mb-4 flex justify-center">
        <span className="flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold"
          style={{ color: INTERVIEWER.color, borderColor: `${INTERVIEWER.color}40`, backgroundColor: `${INTERVIEWER.color}10` }}>
          <BookOpen className="h-3.5 w-3.5" /> 面试官已就位
        </span>
      </div>
      <h2 className="font-display text-2xl font-semibold tracking-tight">开始一轮对话式模拟面试</h2>
      <p className="mt-3 text-sm text-muted-foreground">
        输入您的薄弱知识点，面试官一次只问一题，<br />
        作答后自动评分、给出黄金回答范例并继续追问。
      </p>
      <div className="mt-6 flex items-end gap-2 text-left">
        <MultilineInput
          value={value}
          onChange={onChange}
          onSend={() => onStart(value)}
          placeholder="输入您的薄弱知识点，留空则随机出题…"
        />
        <Button onClick={() => onStart(value)} className="h-11 shrink-0">
          <Send className="mr-1 h-3.5 w-3.5" />开始面试
        </Button>
      </div>
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
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: INTERVIEWER.color }} />
          <span className="text-xs font-semibold" style={{ color: INTERVIEWER.color }}>{INTERVIEWER.label}</span>
        </div>
        {isStreaming && !content && initializing ? (
          <InitIndicator text="面试官正在思考题目" />
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
