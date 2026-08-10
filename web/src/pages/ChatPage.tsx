import { useRef, useEffect, useState } from "react"
import { Send, Square, CornerDownLeft, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { MultilineInput } from "@/components/MultilineInput"
import { InitIndicator, ThinkingPulse } from "@/components/ThinkingIndicator"
import { MarkdownContent } from "@/components/MarkdownContent"
import { useChatStream } from "@/hooks/useChatStream"
import { useChatStore } from "@/store/chatStore"
import { cn } from "@/lib/utils"
import { AGENT_META } from "@/types"
import type { ChatMessage } from "@/types"

let msgId = 0
const nextId = () => `msg-${++msgId}`

/** 判断用户输入是否像 JD（长文本 + 岗位关键词） */
function looksLikeJd(text: string): boolean {
  return text.length > 80 && /职责|要求|职位|JD|岗位|学历|经验|技能|薪资|本科|硕士|工作内容/i.test(text)
}

export default function ChatPage() {
  const [input, setInput] = useState("")
  const {
    messages, addMessage, updateLastAssistant,
    newConversation,
    selectedThreadId, setSelectedThreadId, threadId,
    bumpProfileNonce, bumpThreadNonce,
  } = useChatStore()
  const stream = useChatStream()
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [stream.streamingText, messages])

  useEffect(() => {
    if (stream.status === "done" && stream.doneContent) {
      updateLastAssistant(stream.doneContent)
      if (stream.stage === "match") useChatStore.getState().setLastMatchResult(stream.doneContent)
      bumpProfileNonce()
      bumpThreadNonce()
    }
  }, [stream.status, stream.doneContent, updateLastAssistant, stream.stage, bumpProfileNonce, bumpThreadNonce])

  // 侧边栏选中历史对话时，加载该 thread 的对话消息
  useEffect(() => {
    if (!selectedThreadId) return
    setSelectedThreadId(null)
    stream.reset()
    useChatStore.setState({ messages: [], threadId: selectedThreadId })
    fetch(`/api/memory?thread_id=${selectedThreadId}`)
      .then((r) => r.json())
      .then((entries: Record<string, unknown>[]) => {
        for (const entry of entries) {
          const type = String(entry.type || "")
          const content = String(entry.content || "")
          if (type === "user_message" && content) {
            addMessage({ id: nextId(), role: "user", content })
          } else if (type === "agent_response" && content) {
            addMessage({ id: nextId(), role: "assistant", content, agent: "job_matcher" })
          }
        }
      })
      .catch(() => {})
  }, [selectedThreadId])

  const handleMatch = async (intent: string) => {
    addMessage({ id: nextId(), role: "user", content: intent })
    addMessage({ id: nextId(), role: "assistant", content: "", agent: "job_matcher", streaming: true })
    setInput("")
    await stream.start("/chat/match", { intent, thread_id: threadId })
  }

  const handleResume = async (jdText: string) => {
    addMessage({ id: nextId(), role: "user", content: jdText.slice(0, 100) + (jdText.length > 100 ? "…" : "") })
    addMessage({ id: nextId(), role: "assistant", content: "", agent: "resume_advisor", streaming: true })
    setInput("")
    await stream.start("/chat/resume", { jd_text: jdText, thread_id: threadId })
  }

  const handleSend = () => {
    if (!input.trim() || stream.status === "streaming") return
    // 用户粘贴的 JD（长文本+岗位关键词）-> 走简历顾问
    if (looksLikeJd(input)) {
      handleResume(input)
    } else {
      handleMatch(input)
    }
  }

  const handleNew = () => {
    stream.reset()
    newConversation()
  }

  const lastIsStreaming = stream.status === "streaming"

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-16 shrink-0 items-center justify-between border-b px-6">
        <div>
          <h1 className="font-display text-xl font-semibold">求职对话</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">匹配岗位、定制简历</p>
        </div>
        <Button variant="outline" size="sm" onClick={handleNew}>
          <Plus className="mr-1 h-3.5 w-3.5" />新对话
        </Button>
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6">
        {messages.length === 0 && <EmptyState />}
        <div className="mx-auto max-w-3xl space-y-4">
          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              msg={msg}
              isStreaming={lastIsStreaming && msg.role === "assistant" && (msg.streaming ?? false)}
              streamingText={stream.streamingText}
              thinking={stream.thinking}
              initializing={stream.initializing}
            />
          ))}

          {stream.errorMsg && (
            <Card className="border-destructive">
              <CardContent className="p-4 text-sm text-destructive">{stream.errorMsg}</CardContent>
            </Card>
          )}
        </div>
      </div>

      <div className="shrink-0 border-t bg-card/50 px-6 py-4">
        <div className="mx-auto flex max-w-3xl items-end gap-2">
          <MultilineInput
            value={input}
            onChange={setInput}
            onSend={handleSend}
            disabled={stream.status === "streaming"}
            placeholder="输入求职需求或粘贴目标 JD…"
          />
          {stream.status === "streaming" ? (
            <Button variant="destructive" size="icon" onClick={stream.stop} className="shrink-0">
              <Square className="h-4 w-4" />
            </Button>
          ) : (
            <Button size="icon" onClick={handleSend} disabled={!input.trim()} className="shrink-0">
              <Send className="h-4 w-4" />
            </Button>
          )}
        </div>
        <p className="mx-auto mt-2 flex max-w-3xl items-center gap-1 text-[11px] text-muted-foreground">
          <CornerDownLeft className="h-3 w-3" /> 发送
          <span className="mx-1">·</span>
          Shift + Enter 换行 · 粘贴 JD 自动定制简历
        </p>
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="mx-auto mt-16 max-w-md text-center">
      <div className="mb-6 flex justify-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-full bg-agent-matcher" />
        <span className="h-2.5 w-2.5 rounded-full bg-agent-resume" />
        <span className="h-2.5 w-2.5 rounded-full bg-agent-interviewer" />
        <span className="h-2.5 w-2.5 rounded-full bg-agent-salary" />
        <span className="h-2.5 w-2.5 rounded-full bg-agent-planner" />
      </div>
      <h2 className="font-display text-2xl font-semibold tracking-tight">你的求职顾问团队已就位</h2>
      <p className="mt-3 text-sm text-muted-foreground">
        告诉我们你的方向和背景，匹配官会找到合适的岗位，<br />
        简历顾问再按目标 JD 定制简历。
      </p>
    </div>
  )
}

function MessageBubble({ msg, isStreaming, streamingText, thinking, initializing }: {
  msg: ChatMessage
  isStreaming: boolean
  streamingText: string
  thinking: boolean
  initializing: boolean
}) {
  const isUser = msg.role === "user"
  const content = isStreaming ? streamingText : msg.content
  const meta = msg.agent ? AGENT_META[msg.agent] : null

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
        {meta && (
          <div className="mb-1.5 flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: meta.color }} />
            <span className="text-xs font-semibold" style={{ color: meta.color }}>{meta.label}</span>
          </div>
        )}
        {isStreaming && !content && initializing ? (
          <InitIndicator />
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
