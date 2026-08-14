import { useEffect, useRef, useState } from "react"
import { Send, Square, Plus, Users, ChevronDown } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { MultilineInput } from "@/components/MultilineInput"
import { InputHint } from "@/components/InputHint"
import { InitIndicator, ThinkingPulse } from "@/components/ThinkingIndicator"
import { MarkdownContent } from "@/components/MarkdownContent"
import { JumpToLatest } from "@/components/JumpToLatest"
import { useChatScroll } from "@/hooks/useChatScroll"
import { useThreadStore } from "@/store/threadStore"
import { IDLE_SESSION, useStreamStore, type StreamSession } from "@/store/streamStore"
import { AGENT_META, CONSULT_AGENTS, CONSULT_INPUT_FIELDS, ORCHESTRATOR_META, type ConsultCall } from "@/types"
import { ConsultFormDialog } from "@/components/ConsultFormDialog"
import { cn } from "@/lib/utils"
import { apiFetch } from "@/lib/auth"

let msgId = 0
const nextId = () => `consult-${++msgId}`

interface ConsultMessage {
  id: string
  role: "user" | "assistant"
  content?: string
  opinions?: Record<string, string>
  calls?: ConsultCall[]
}

export default function ConsultPage() {
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<ConsultMessage[]>([])
  // 资料填写框：一次会话里用户主动关闭后不再弹出（提交/手动发送时后端流会重置 pendingInput）
  const [formDismissed, setFormDismissed] = useState(false)
  const lastAssistantIdRef = useRef<string | null>(null)
  const currentThreadId = useThreadStore((s) => s.currentThreadByModule.consult)
  // 每会话独立流：切换会话不影响其他会话正在进行的回答
  const stream = useStreamStore((s) => s.sessions[currentThreadId] ?? IDLE_SESSION)
  const startStream = useStreamStore((s) => s.start)
  const stopStream = useStreamStore((s) => s.stop)
  const { scrollRef, showJumpToLatest, jumpToLatest } = useChatScroll([stream.streamingText, stream.agentChunks, messages])

  // 流结束（done / 手动停止 / 出错）后把结果落进对话历史
  useEffect(() => {
    if (stream.status === "streaming") return
    if (stream.status === "idle" && !stream.streamingText && !stream.doneContent) return
    setMessages((prev) =>
      prev.map((m) =>
        m.id === lastAssistantIdRef.current && !m.content
          ? {
              ...m,
              content: stream.doneContent || stream.streamingText || "",
              opinions: stream.opinions,
              calls: stream.calls,
            }
          : m
      )
    )
  }, [stream.status, stream.doneContent, stream.streamingText, stream.opinions, stream.calls])

  // 当前会话变化（选中历史 / 新建）时加载该 thread 的消息
  useEffect(() => {
    const tid = currentThreadId
    lastAssistantIdRef.current = null
    setMessages([])
    apiFetch(`/api/memory?thread_id=${tid}`)
      .then((r) => r.json())
      .then((entries: Record<string, unknown>[]) => {
        const msgs: ConsultMessage[] = []
        for (const entry of entries) {
          const type = String(entry.type || "")
          const content = String(entry.content || "")
          if (type === "user_message" && content) msgs.push({ id: nextId(), role: "user", content })
          else if (type === "agent_response" && content) {
            msgs.push({
              id: nextId(),
              role: "assistant",
              content,
              calls: Array.isArray(entry.consult_calls) ? (entry.consult_calls as ConsultCall[]) : undefined,
            })
          }
        }
        // 切回一个仍在流式回答的会话：补一个流式占位气泡（会诊渲染用 lastAssistantIdRef 定位）
        const live = useStreamStore.getState().sessions[tid]
        if (live && live.status === "streaming") {
          const id = nextId()
          lastAssistantIdRef.current = id
          setMessages([...msgs, { id, role: "assistant" }])
        } else {
          setMessages(msgs)
        }
        jumpToLatest()
      })
      .catch(() => {})
  }, [currentThreadId, jumpToLatest])

  const sendQuestion = async (q: string, profile?: Record<string, string>) => {
    const trimmed = q.trim()
    if (!trimmed || stream.status === "streaming") return
    const isFirst = messages.length === 0
    const id = nextId()
    lastAssistantIdRef.current = id
    setMessages((prev) => [...prev, { id: nextId(), role: "user", content: trimmed }, { id, role: "assistant" }])
    setInput("")
    jumpToLatest()
    if (isFirst) useThreadStore.getState().touchThread("consult", currentThreadId, trimmed)
    await startStream(currentThreadId, "/consult", {
      question: trimmed,
      thread_id: currentThreadId,
      ...(profile ? { profile } : {}),
    })
  }

  const handleSend = () => {
    void sendQuestion(input)
  }

  // 资料填写框提交：把结构化字段拼成可读消息 + 原样 profile 传给后端，
  // 后端据此直接给出规划，不再追问。
  const handleFormSubmit = (values: Record<string, string>) => {
    const fields = stream.pendingInput?.fields.length ? stream.pendingInput.fields : CONSULT_INPUT_FIELDS
    const parts: string[] = []
    for (const f of fields) {
      const v = (values[f.id] ?? "").trim()
      if (v) parts.push(`${f.label}：${v}`)
    }
    const q = parts.length ? `我补充一下我的求职信息：${parts.join("；")}` : "我补充了求职信息，请继续"
    setFormDismissed(true)
    void sendQuestion(q, values)
  }

  const handleNew = () => {
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
          <p className="mt-0.5 text-xs text-muted-foreground">总调度官自动调度顾问，综合给出建议</p>
        </div>
        <Button variant="outline" size="sm" onClick={handleNew}>
          <Plus className="mr-1 h-3.5 w-3.5" />新对话
        </Button>
      </header>

      <div className="relative flex-1 overflow-hidden">
        <div ref={scrollRef} className="h-full overflow-y-auto px-6 py-6">
          {messages.length === 0 && stream.status === "idle" && <EmptyState />}
          <div className="mx-auto max-w-3xl space-y-4">
            {messages.map((msg) =>
              msg.role === "user" ? (
                <UserBubble key={msg.id} content={msg.content || ""} />
              ) : isLive(msg) ? (
                <LiveAssistant key={msg.id} stream={stream} />
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
            <Button variant="destructive" size="icon" onClick={() => stopStream(currentThreadId)} className="h-11 w-11 shrink-0">
              <Square className="h-4 w-4" />
            </Button>
          ) : (
            <Button
              size="icon"
              onClick={handleSend}
              disabled={!input.trim()}
              className="h-11 w-11 shrink-0"
            >
              <Send className="h-4 w-4" />
            </Button>
          )}
        </div>
        <InputHint tip="总调度官自动调度顾问，综合给出建议" />
      </div>

      <ConsultFormDialog
        open={!!stream.pendingInput && stream.status !== "streaming" && !formDismissed}
        message={stream.pendingInput?.message}
        fields={stream.pendingInput?.fields ?? []}
        onClose={() => setFormDismissed(true)}
        onSubmit={handleFormSubmit}
      />
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

function LiveAssistant({ stream }: { stream: StreamSession }) {
  const live = stream.status === "streaming"
  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[85%] space-y-2">
        {live && stream.stage === "consult" && (
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
            总调度官正在分析并调度顾问
          </p>
        )}
        {stream.dispatch && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>第 {stream.dispatch.round} 轮调度：</span>
            {stream.dispatch.agents.map((id) => {
              const meta = AGENT_META[id] ?? { label: id, color: "#78716C" }
              return (
                <span
                  key={id}
                  className="flex items-center gap-1.5 rounded-full border bg-card px-2.5 py-0.5"
                >
                  <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: meta.color }} />
                  {meta.label}
                </span>
              )
            })}
          </div>
        )}
        {(stream.stage === "synthesis" || stream.streamingText || stream.doneContent) && (
          <Card className="stream-fade-in bg-primary/5">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm font-semibold" style={{ color: ORCHESTRATOR_META.color }}>
                <Users className="h-3.5 w-3.5" />{ORCHESTRATOR_META.label}结论
              </CardTitle>
            </CardHeader>
            <CardContent>
              {live && !stream.streamingText && !stream.doneContent ? (
                <InitIndicator text="正在生成总调度官结论" />
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

function HistoryAssistant({ msg }: { msg: ConsultMessage }) {
  const opinions = msg.opinions ?? {}
  const calls = msg.calls ?? []
  const ids = Object.keys(opinions)
  const groups = calls.reduce<Record<number, ConsultCall[]>>((acc, call) => {
    ;(acc[call.round] ||= []).push(call)
    return acc
  }, {})
  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[85%] space-y-2">
        {Object.keys(groups).length > 0 && (
          <details className="group rounded-lg border bg-card/60 px-3 py-2">
            <summary className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
              查看调度过程（{calls.length} 次调用）
            </summary>
            <div className="mt-2 space-y-2">
              {Object.entries(groups).map(([round, roundCalls]) => (
                <div key={round} className="space-y-1.5">
                  <p className="text-[11px] font-semibold text-muted-foreground">第 {round} 轮</p>
                  {roundCalls.map((call) => {
                    const meta = AGENT_META[call.agent] ?? { label: call.agent, color: "#78716C" }
                    return (
                      <div key={`${round}-${call.agent}`} className="rounded-md bg-muted/50 p-2.5">
                        <div className="mb-1 flex items-center gap-1.5">
                          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: meta.color }} />
                          <span className="text-xs font-semibold" style={{ color: meta.color }}>{meta.label}</span>
                        </div>
                        {call.task && <p className="mb-1 text-[11px] text-muted-foreground">{call.task}</p>}
                        <MarkdownContent className="text-[13px]">{call.content}</MarkdownContent>
                      </div>
                    )
                  })}
                </div>
              ))}
            </div>
          </details>
        )}
        {ids.length > 0 && calls.length === 0 && (
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
            <CardTitle className="flex items-center gap-2 text-sm font-semibold" style={{ color: ORCHESTRATOR_META.color }}>
              <Users className="h-3.5 w-3.5" />{ORCHESTRATOR_META.label}结论
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
      <p className="mt-3 text-sm text-muted-foreground">输入问题，总调度官会自动选择合适的顾问并综合给你建议。</p>
    </div>
  )
}
