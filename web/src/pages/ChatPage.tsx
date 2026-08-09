import { useRef, useEffect, useState } from "react"
import { Send, Square, CornerDownLeft, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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

export default function ChatPage() {
  const [input, setInput] = useState("")
  const {
    messages, addMessage, updateLastAssistant,
    selectedJd, setSelectedJd,
    lastMatchResult, setLastMatchResult,
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
      if (stream.stage === "match") setLastMatchResult(stream.doneContent)
      bumpProfileNonce()
      bumpThreadNonce()
    }
  }, [stream.status, stream.doneContent, updateLastAssistant, setLastMatchResult, stream.stage, bumpProfileNonce, bumpThreadNonce])

  // 侧边栏选中历史对话时，加载该 thread 的对话消息
  useEffect(() => {
    if (!selectedThreadId) return
    setSelectedThreadId(null)
    stream.reset()
    useChatStore.setState({ messages: [], selectedJd: "", lastMatchResult: "", threadId: selectedThreadId })
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
          // 跳过 job_match / interview_qa 等结构化记忆条目
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

  const handleResume = async () => {
    if (!selectedJd.trim()) return
    addMessage({ id: nextId(), role: "user", content: `[选择 JD] ${selectedJd.slice(0, 80)}…` })
    addMessage({ id: nextId(), role: "assistant", content: "", agent: "resume_advisor", streaming: true })
    await stream.start("/chat/resume", { jd_text: selectedJd, thread_id: threadId })
    setSelectedJd("")
  }

  const handleSend = () => {
    if (!input.trim() || stream.status === "streaming") return
    handleMatch(input)
  }

  const handleNew = () => {
    stream.reset()
    newConversation()
  }

  const lastIsStreaming = stream.status === "streaming"
  // JD 选择器：仅在 agent 真正返回匹配结果（含"匹配度"或"匹配分"关键词）时显示
  // 追问类回复（如"你的方向是什么？"）不弹 JD 选择器
  const matchContent = stream.doneContent || lastMatchResult
  const isMatchResult = matchContent && /匹配[度分]|0\.\d|岗位.*列表|公司.*title/i.test(matchContent)
  const showJdSelector = !selectedJd && !lastIsStreaming && isMatchResult
  const jdTarget = matchContent

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-16 shrink-0 items-center justify-between border-b px-6">
        <div>
          <h1 className="font-display text-xl font-semibold">求职对话</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">匹配岗位、选择 JD、定制简历</p>
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

          {showJdSelector && jdTarget && (
            <JDSelector onSelect={(jd) => setSelectedJd(jd)} onCustomize={handleResume} />
          )}

          {selectedJd && !lastIsStreaming && (
            <Card className="bg-accent/5">
              <CardContent className="flex items-start gap-3 p-4">
                <div className="flex-1">
                  <p className="mb-1 text-xs font-semibold text-accent">已选目标 JD</p>
                  <p className="text-sm whitespace-pre-wrap">{selectedJd}</p>
                </div>
                <Button size="sm" onClick={handleResume} className="shrink-0">定制简历</Button>
              </CardContent>
            </Card>
          )}

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
            placeholder="输入求职需求…"
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
          Shift + Enter 换行 · 支持多行粘贴
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

function JDSelector({ onSelect, onCustomize }: {
  onSelect: (jd: string) => void
  onCustomize: () => void
}) {
  const [jd, setJd] = useState("")
  return (
    <Card className="stream-fade-in">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-semibold">选择目标 JD，简历顾问来定制</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-muted-foreground">从上方匹配结果中复制你感兴趣的岗位 JD，粘贴到下方</p>
        <MultilineInput
          value={jd}
          onChange={setJd}
          onSend={() => { onSelect(jd); onCustomize() }}
          placeholder="粘贴目标岗位的 JD 内容…"
          className="text-sm"
        />
        <Button size="sm" disabled={!jd.trim()} onClick={() => { onSelect(jd); onCustomize() }} className="shrink-0">
          定制简历
        </Button>
      </CardContent>
    </Card>
  )
}
