import { useEffect, useRef, useState } from "react"
import { Loader2, Send, Square, Plus, Users, ChevronDown } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { MultilineInput } from "@/components/MultilineInput"
import { InitIndicator, ThinkingPulse } from "@/components/ThinkingIndicator"
import { MarkdownContent } from "@/components/MarkdownContent"
import { JumpToLatest } from "@/components/JumpToLatest"
import { useChatStream } from "@/hooks/useChatStream"
import { useChatScroll } from "@/hooks/useChatScroll"
import { useThreadStore } from "@/store/threadStore"
import { AGENT_META, CONSULT_AGENTS } from "@/types"
import { cn } from "@/lib/utils"

let msgId = 0
const nextId = () => `consult-${++msgId}`

interface ConsultMessage {
  id: string
  role: "user" | "assistant"
  content?: string
  opinions?: Record<string, string>
}

export default function ConsultPage() {
  const [input, setInput] = useState("")
  const [selectedAgents, setSelectedAgents] = useState<string[]>(["salary_negotiator", "career_planner"])
  const [messages, setMessages] = useState<ConsultMessage[]>([])
  const lastAssistantIdRef = useRef<string | null>(null)
  const stream = useChatStream()
  const { scrollRef, showJumpToLatest, jumpToLatest } = useChatScroll([stream.streamingText, stream.agentChunks, messages])
  const currentThreadId = useThreadStore((s) => s.currentThreadByModule.consult)

  // 流结束（done / 手动停止 / 出错）后把结果落进对话历史
  useEffect(() => {
    if (stream.status === "streaming") return
    if (stream.status === "idle" && !stream.streamingText && !stream.doneContent) return
    setMessages((prev) =>
      prev.map((m) =>
        m.id === lastAssistantIdRef.current && !m.content
          ? { ...m, content: stream.doneContent || stream.streamingText || "", opinions: stream.opinions }
          : m
      )
    )
    useThreadStore.getState().bumpNonce()
  }, [stream.status, stream.doneContent, stream.streamingText, stream.opinions])

  // 当前会话变化（选中历史 / 新建）时加载该 thread 的消息
  useEffect(() => {
    const tid = currentThreadId
    stream.reset()
    lastAssistantIdRef.current = null
    setMessages([])
    fetch(`/api/memory?thread_id=${tid}`)
      .then((r) => r.json())
      .then((entries: Record<string, unknown>[]) => {
        const msgs: ConsultMessage[] = []
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

  const toggleAgent = (id: string) => {
    setSelectedAgents((prev) => (prev.includes(id) ? prev.filter((a) => a !== id) : [...prev, id]))
  }

  const handleSend = async () => {
    const q = input.trim()
    if (!q || stream.status === "streaming" || selectedAgents.length === 0) return
    const isFirst = messages.length === 0
    const id = nextId()
    lastAssistantIdRef.current = id
    setMessages((prev) => [...prev, { id: nextId(), role: "user", content: q }, { id, role: "assistant" }])
    setInput("")
    jumpToLatest()
    if (isFirst) useThreadStore.getState().touchThread("consult", currentThreadId, q)
    await stream.start("/consult", { question: q, agents: selectedAgents, thread_id: currentThreadId })
  }

  const handleNew = () => {
    stream.reset()
    setMessages([])
    lastAssistantIdRef.current = null
    useThreadStore.getState().registerThread("consult")
  }

  const isLive = (m: ConsultMessage) => m.id === lastAssistantIdRef.current && !m.content

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-16 shrink-0 items-center justify-between border-b px-6">
        <div>
          <h1 className="font-display text-xl font-semibold">会诊</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">多位顾问并行分析，综合给出建议</p>
        </div>
        <Button variant="outline" size="sm" onClick={handleNew}>
          <Plus className="mr-1 h-3.5 w-3.5" />新对话
        </Button>
      </header>

      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b bg-card/50 px-6 py-2.5">
        <span className="text-xs font-medium text-muted-foreground">参与顾问</span>
        {CONSULT_AGENTS.map((agent) => {
          const active = selectedAgents.includes(agent.id)
          return (
            <button
              key={agent.id}
              onClick={() => toggleAgent(agent.id)}
              disabled={stream.status === "streaming"}
              className={cn(
                "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-all",
                active ? "text-white" : "border-border bg-card hover:bg-muted"
              )}
              style={active ? { backgroundColor: agent.color, borderColor: agent.color } : {}}
            >
              <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: active ? "white" : agent.color }} />
              {agent.label}
            </button>
          )
        })}
      </div>

      <div className="relative flex-1 overflow-hidden">
        <div ref={scrollRef} className="h-full overflow-y-auto px-6 py-6">
          {messages.length === 0 && stream.status === "idle" && <EmptyState />}
          <div className="mx-auto max-w-3xl space-y-4">
            {messages.map((msg) =>
              msg.role === "user" ? (
                <UserBubble key={msg.id} content={msg.content || ""} />
              ) : isLive(msg) ? (
                <LiveAssistant key={msg.id} agents={selectedAgents} stream={stream} />
              ) : (
                <HistoryAssistant key={msg.id} msg={msg} />
              )
            )}
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
            placeholder="输入需要会诊的问题…"
          />
          {stream.status === "streaming" ? (
            <Button variant="destructive" size="icon" onClick={stream.stop} className="h-11 w-11 shrink-0">
              <Square className="h-4 w-4" />
            </Button>
          ) : (
            <Button
              size="icon"
              onClick={handleSend}
              disabled={!input.trim() || selectedAgents.length === 0}
              className="h-11 w-11 shrink-0"
            >
              <Send className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-lg rounded-br-sm bg-primary px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap text-primary-foreground">
        {content}
      </div>
    </div>
  )
}

function LiveAssistant({ agents, stream }: { agents: string[]; stream: ReturnType<typeof useChatStream> }) {
  const live = stream.status === "streaming"
  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[85%] space-y-2">
        {live && stream.stage === "consult" && (
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
            各顾问正在并行分析
          </p>
        )}
        <div className="grid gap-2 sm:grid-cols-2">
          {agents.map((id) => (
            <LiveOpinionCard key={id} id={id} content={stream.agentChunks[id] ?? ""} streaming={live} />
          ))}
        </div>
        {(stream.stage === "synthesis" || stream.streamingText || stream.doneContent) && (
          <Card className="stream-fade-in bg-primary/5">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm font-semibold text-primary">
                <Users className="h-3.5 w-3.5" />综合结论
              </CardTitle>
            </CardHeader>
            <CardContent>
              {live && !stream.streamingText && !stream.doneContent ? (
                <InitIndicator text="正在生成综合结论" />
              ) : (
                <>
                  <MarkdownContent className={cn(live && !stream.thinking && "typing-cursor")}>
                    {stream.doneContent || stream.streamingText}
                  </MarkdownContent>
                  {live && stream.thinking && <ThinkingPulse />}
                </>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}

function LiveOpinionCard({ id, content, streaming }: { id: string; content: string; streaming: boolean }) {
  const meta = AGENT_META[id] ?? { label: id, color: "#78716C" }
  return (
    <Card className="stream-fade-in">
      <CardHeader className="pb-1">
        <div className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: meta.color }} />
          <span className="text-xs font-semibold" style={{ color: meta.color }}>{meta.label}</span>
          {streaming && !content && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
        </div>
      </CardHeader>
      <CardContent className="text-[13px]">
        {content ? (
          <MarkdownContent>{content}</MarkdownContent>
        ) : (
          <p className="text-xs text-muted-foreground">分析中…</p>
        )}
      </CardContent>
    </Card>
  )
}

function HistoryAssistant({ msg }: { msg: ConsultMessage }) {
  const opinions = msg.opinions ?? {}
  const ids = Object.keys(opinions)
  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[85%] space-y-2">
        {ids.length > 0 && (
          <details className="group rounded-lg border bg-card/60 px-3 py-2">
            <summary className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
              查看 {ids.length} 位顾问的独立意见
            </summary>
            <div className="mt-2 space-y-2">
              {ids.map((id) => {
                const meta = AGENT_META[id] ?? { label: id, color: "#78716C" }
                return (
                  <div key={id} className="rounded-md bg-muted/50 p-2.5">
                    <div className="mb-1 flex items-center gap-1.5">
                      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: meta.color }} />
                      <span className="text-xs font-semibold" style={{ color: meta.color }}>{meta.label}</span>
                    </div>
                    <MarkdownContent className="text-[13px]">{opinions[id]}</MarkdownContent>
                  </div>
                )
              })}
            </div>
          </details>
        )}
        <Card className="stream-fade-in bg-primary/5">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold text-primary">
              <Users className="h-3.5 w-3.5" />综合结论
            </CardTitle>
          </CardHeader>
          <CardContent>
            <MarkdownContent>{msg.content || ""}</MarkdownContent>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="mx-auto mt-16 max-w-md text-center">
      <div className="mb-6 flex justify-center gap-1.5">
        {CONSULT_AGENTS.map((a) => (
          <span key={a.id} className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: a.color }} />
        ))}
      </div>
      <h2 className="font-display text-2xl font-semibold tracking-tight">你的求职顾问团队已就位</h2>
      <p className="mt-3 text-sm text-muted-foreground">选择上方顾问，输入问题，他们会并行分析后综合给你建议。</p>
    </div>
  )
}
