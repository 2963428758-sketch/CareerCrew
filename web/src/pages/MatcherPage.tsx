import { useEffect, useState } from "react"
import { Send, Square, CornerDownLeft, Target, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { MultilineInput } from "@/components/MultilineInput"
import { InitIndicator, ThinkingPulse } from "@/components/ThinkingIndicator"
import { MarkdownContent } from "@/components/MarkdownContent"
import { useChatStream } from "@/hooks/useChatStream"
import { useChatScroll } from "@/hooks/useChatScroll"
import { JumpToLatest } from "@/components/JumpToLatest"
import { useThreadStore } from "@/store/threadStore"
import { AGENT_META } from "@/types"
import { cn } from "@/lib/utils"

interface MatcherMessage {
  id: string
  role: "user" | "assistant"
  content: string
  streaming?: boolean
}

let msgId = 0
const nextId = () => `match-msg-${++msgId}`

export default function MatcherPage() {
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<MatcherMessage[]>([])
  const stream = useChatStream()
  const { scrollRef, showJumpToLatest, jumpToLatest } = useChatScroll([stream.streamingText, messages])
  const currentThreadId = useThreadStore((s) => s.currentThreadByModule.matcher)
  const meta = AGENT_META.job_matcher

  useEffect(() => {
    if (stream.status === "done" && stream.doneContent) {
      setMessages((prev) => {
        const msgs = [...prev]
        for (let i = msgs.length - 1; i >= 0; i--) {
          if (msgs[i].role === "assistant" && msgs[i].streaming) {
            msgs[i] = { ...msgs[i], content: stream.doneContent, streaming: false }
            break
          }
        }
        return msgs
      })
      useThreadStore.getState().bumpNonce()
    }
  }, [stream.status, stream.doneContent])

  // 当前会话变化（选中历史 / 新建）时加载该 thread 的消息
  useEffect(() => {
    const tid = currentThreadId
    stream.reset()
    setMessages([])
    fetch(`/api/memory?thread_id=${tid}`)
      .then((r) => r.json())
      .then((entries: Record<string, unknown>[]) => {
        const msgs: MatcherMessage[] = []
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

  const handleSend = async () => {
    const intent = input
    if (!intent.trim() || stream.status === "streaming") return
    const isFirst = messages.length === 0
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", content: intent },
      { id: nextId(), role: "assistant", content: "", streaming: true },
    ])
    setInput("")
    jumpToLatest()
    if (isFirst) useThreadStore.getState().touchThread("matcher", currentThreadId, intent)
    await stream.start("/chat/match", { intent, thread_id: currentThreadId })
  }

  const handleNew = () => {
    if (stream.status === "streaming") stream.stop()
    stream.reset()
    setMessages([])
    useThreadStore.getState().registerThread("matcher")
  }

  const lastIsStreaming = stream.status === "streaming"

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-16 shrink-0 items-center justify-between border-b px-6">
        <div>
          <h1 className="font-display text-xl font-semibold">职位匹配</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">输入求职方向,匹配官检索岗位</p>
        </div>
        <Button variant="outline" size="sm" onClick={handleNew}>
          <Plus className="mr-1 h-3.5 w-3.5" />新对话
        </Button>
      </header>

      <div className="relative flex-1 overflow-hidden">
        <div ref={scrollRef} className="h-full overflow-y-auto px-6 py-6">
          {messages.length === 0 && (
            <div className="mx-auto mt-16 max-w-md text-center">
              <div className="mb-6 flex justify-center">
                <Target className="h-10 w-10" style={{ color: meta.color }} />
              </div>
              <h2 className="font-display text-2xl font-semibold tracking-tight">告诉匹配官你的方向</h2>
              <p className="mt-3 text-sm text-muted-foreground">
                输入求职方向与背景后，
                <br />
                匹配官会搜索猎聘真实岗位并评估匹配度。
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
            onSend={handleSend}
            disabled={stream.status === "streaming"}
            placeholder="输入求职方向与背景，匹配官将自动检索岗位"
          />
          {stream.status === "streaming" ? (
            <Button variant="destructive" size="icon" onClick={stream.stop} className="h-11 w-11 shrink-0">
              <Square className="h-4 w-4" />
            </Button>
          ) : (
            <Button size="icon" onClick={handleSend} disabled={!input.trim()} className="h-11 w-11 shrink-0">
              <Send className="h-4 w-4" />
            </Button>
          )}
        </div>
        <p className="mx-auto mt-2 flex max-w-3xl items-center gap-1 text-[11px] text-muted-foreground">
          <CornerDownLeft className="h-3 w-3" /> 发送
          <span className="mx-1">·</span>
          Shift + Enter 换行
        </p>
      </div>
    </div>
  )
}

function MessageBubble({ msg, isStreaming, streamingText, thinking, initializing }: {
  msg: MatcherMessage
  isStreaming: boolean
  streamingText: string
  thinking: boolean
  initializing: boolean
}) {
  const isUser = msg.role === "user"
  const meta = AGENT_META.job_matcher
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
