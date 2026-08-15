import { useEffect, useState } from "react"
import { Send, Square, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { MultilineInput } from "@/components/MultilineInput"
import { InputHint } from "@/components/InputHint"
import { InitIndicator, ThinkingPulse } from "@/components/ThinkingIndicator"
import { MarkdownContent } from "@/components/MarkdownContent"
import { useChatScroll } from "@/hooks/useChatScroll"
import { JumpToLatest } from "@/components/JumpToLatest"
import { useChatStore } from "@/store/chatStore"
import { useThreadStore } from "@/store/threadStore"
import { IDLE_SESSION, useStreamStore } from "@/store/streamStore"
import { cn } from "@/lib/utils"
import { apiFetch } from "@/lib/auth"
import { AGENT_META } from "@/types"
import type { ChatMessage } from "@/types"

let msgId = 0
const nextId = () => `msg-${++msgId}`

export default function ChatPage() {
  const [input, setInput] = useState("")
  const {
    messages, addMessage, updateLastAssistant,
    newConversation,
    bumpProfileNonce,
  } = useChatStore()
  const currentThreadId = useThreadStore((s) => s.currentThreadByModule.chat)
  // 每会话独立流：切换会话不影响其他会话正在进行的回答
  const stream = useStreamStore((s) => s.sessions[currentThreadId] ?? IDLE_SESSION)
  const startStream = useStreamStore((s) => s.start)
  const stopStream = useStreamStore((s) => s.stop)
  const { scrollRef, showJumpToLatest, jumpToLatest } = useChatScroll([stream.streamingText, messages])
  const initializing = stream.status === "streaming" && stream.streamingText === "" && Object.keys(stream.agentChunks).length === 0

  useEffect(() => {
    if (stream.status === "done" && stream.doneContent) {
      updateLastAssistant(stream.doneContent)
      if (stream.stage === "match") useChatStore.getState().setLastMatchResult(stream.doneContent)
      bumpProfileNonce()
    }
  }, [stream.status, stream.doneContent, updateLastAssistant, stream.stage, bumpProfileNonce])

  // 当前会话变化（侧边栏选中历史 / 新建会话）时加载该 thread 的消息
  useEffect(() => {
    const tid = currentThreadId
    useChatStore.setState({ messages: [], threadId: tid })
    apiFetch(`/api/memory?thread_id=${tid}`)
      .then((r) => r.json())
      .then((entries: Record<string, unknown>[]) => {
        const msgs: ChatMessage[] = []
        for (const entry of entries) {
          const type = String(entry.type || "")
          const content = String(entry.content || "")
          if (type === "user_message" && content) {
            msgs.push({ id: nextId(), role: "user", content })
          } else if (type === "agent_response" && content) {
            msgs.push({ id: nextId(), role: "assistant", content, agent: "career_planner" })
          }
        }
        useChatStore.setState({ messages: msgs, threadId: tid })
        // 切回一个仍在流式回答的会话：补一个流式占位气泡
        const live = useStreamStore.getState().sessions[tid]
        if (live && live.status === "streaming") {
          useChatStore.getState().addMessage({
            id: nextId(), role: "assistant", content: "",
            agent: "career_planner",
            streaming: true,
          })
        }
        jumpToLatest()
      })
      .catch(() => {})
  }, [currentThreadId, jumpToLatest])

  const handlePlan = async (text: string) => {
    const isFirst = useChatStore.getState().messages.length === 0
    addMessage({ id: nextId(), role: "user", content: text })
    addMessage({ id: nextId(), role: "assistant", content: "", agent: "career_planner", streaming: true })
    setInput("")
    jumpToLatest()
    if (isFirst) useThreadStore.getState().touchThread("chat", currentThreadId, text)
    await startStream(currentThreadId, "/chat/plan", { intent: text, thread_id: currentThreadId })
  }

  const handleSend = () => {
    if (!input.trim() || stream.status === "streaming") return
    handlePlan(input)
  }

  const handleNew = () => {
    newConversation()
    useThreadStore.getState().registerThread("chat")
  }

  const lastIsStreaming = stream.status === "streaming"

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-16 shrink-0 items-center justify-between border-b px-6">
        <div>
          <h1 className="font-display text-xl font-semibold">求职规划</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">职业规划师 · 求职规划</p>
        </div>
        <Button variant="outline" size="sm" onClick={handleNew}>
          <Plus className="mr-1 h-3.5 w-3.5" />新对话
        </Button>
      </header>

      <div className="relative flex-1 overflow-hidden">
        <div ref={scrollRef} className="h-full overflow-y-auto px-6 py-6">
          {messages.length === 0 && <EmptyState />}
          <div className="mx-auto max-w-3xl space-y-4">
            {messages.map((msg) => (
              <MessageBubble
                key={msg.id}
                msg={msg}
                isStreaming={lastIsStreaming && msg.role === "assistant" && (msg.streaming ?? false)}
                streamingText={stream.streamingText}
                thinking={stream.thinking}
                initializing={initializing}
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
            placeholder="聊聊你的求职方向与背景…"
          />
          {stream.status === "streaming" ? (
            <Button variant="destructive" size="icon" onClick={() => stopStream(currentThreadId)} className="h-11 w-11 shrink-0">
              <Square className="h-4 w-4" />
            </Button>
          ) : (
            <Button size="icon" onClick={handleSend} disabled={!input.trim()} className="h-11 w-11 shrink-0">
              <Send className="h-4 w-4" />
            </Button>
          )}
        </div>
        <InputHint tip="规划师帮你制定求职规划" />
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
        告诉规划师你的方向和背景，<br />
        帮你建立能力画像、确定目标公司、制定阶段规划。
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
