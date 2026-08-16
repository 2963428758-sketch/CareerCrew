import { useEffect, useMemo, useRef, useState } from "react"
import { Users, ChevronDown } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { PromptComposer } from "@/components/prompt/PromptComposer"
import { InitIndicator, ThinkingPulse } from "@/components/ThinkingIndicator"
import { MarkdownContent } from "@/components/MarkdownContent"
import { AgentPanel } from "@/components/agent/AgentThread"
import { EmptyState, AgentDots } from "@/components/workspace/EmptyState"
import { JumpToLatest } from "@/components/JumpToLatest"
import { ConversationRail } from "@/components/conversation/ConversationRail"
import { ConversationHeader } from "@/components/conversation/ConversationHeader"
import { TurnSection } from "@/components/conversation/TurnSection"
import { ToastBubble } from "@/components/conversation/ToastBubble"
import { FeedbackArea } from "@/components/conversation/FeedbackArea"
import { groupTurns } from "@/components/conversation/turn"
import { useConversationNavigation } from "@/hooks/useConversationNavigation"
import { useToast } from "@/hooks/useToast"
import { useChatScroll } from "@/hooks/useChatScroll"
import { useThreadStore } from "@/store/threadStore"
import { IDLE_SESSION, useStreamStore, type StreamSession } from "@/store/streamStore"
import { AGENT_META, CONSULT_AGENTS, CONSULT_INPUT_FIELDS, ORCHESTRATOR_META, type ConsultCall, type MessageFeedback } from "@/types"
import { ConsultFormDialog } from "@/components/ConsultFormDialog"
import { cn } from "@/lib/utils"
import { restoreHistory } from "@/lib/historyRestore"

let msgId = 0
const nextId = () => `consult-${++msgId}`

interface ConsultMessage {
  id: string
  role: "user" | "assistant"
  content?: string
  opinions?: Record<string, string>
  calls?: ConsultCall[]
  messageId?: string
  turnId?: string
  runId?: string
}

export default function ConsultPage() {
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<ConsultMessage[]>([])
  // 资料填写框：关闭状态按会话（thread_id）保存——一次会话里用户主动关闭后不再弹出，
  // 切换/新建会话回到各自状态（新会话默认未关闭，会正常弹出）。
  const [dismissedThreads, setDismissedThreads] = useState<Record<string, boolean>>({})
  const lastAssistantIdRef = useRef<string | null>(null)
  const currentThreadId = useThreadStore((s) => s.currentThreadByModule.consult)
  // 会话标题：首条消息后由 touchThread 落库，展示在 Header 左侧
  const threadTitle = useThreadStore((s) =>
    s.threadsByModule.consult?.find((t) => t.thread_id === s.currentThreadByModule.consult)?.title
  )
  const formDismissed = dismissedThreads[currentThreadId] ?? false
  // 每会话独立流：切换会话不影响其他会话正在进行的回答
  const stream = useStreamStore((s) => s.sessions[currentThreadId] ?? IDLE_SESSION)
  const startStream = useStreamStore((s) => s.start)
  const stopStream = useStreamStore((s) => s.stop)
  const { scrollRef, showJumpToLatest, jumpToLatest } = useChatScroll([stream.streamingText, stream.agentChunks, messages])

  // ── Turn 分组 + Anchor Rail 导航 ──
  const turns = useMemo(() => groupTurns(messages), [messages])
  const turnIds = useMemo(() => turns.map((t) => t.user.id), [turns])
  const { activeId, selectTurn, highlightId } = useConversationNavigation(turnIds, scrollRef)
  const { toast, showToast } = useToast()
  const composerRef = useRef<HTMLTextAreaElement | null>(null)

  // 流结束（done / 手动停止 / 出错）后把结果落进对话历史
  useEffect(() => {
    if (stream.status === "streaming") return
    if (stream.status === "error") {
      // 流出错：移除未填充的空助手占位气泡，避免残留空气泡
      setMessages((prev) =>
        lastAssistantIdRef.current
          ? prev.filter((m) => m.id !== lastAssistantIdRef.current)
          : prev
      )
      lastAssistantIdRef.current = null
      return
    }
    if (stream.status === "idle" && !stream.streamingText && !stream.doneContent) return
    setMessages((prev) =>
      prev.map((m) =>
        m.id === lastAssistantIdRef.current && !m.content
          ? {
              ...m,
              content: stream.doneContent || stream.streamingText || "",
              opinions: stream.opinions,
              calls: stream.calls,
              messageId: stream.doneIds?.messageId,
              turnId: stream.doneIds?.turnId,
              runId: stream.doneIds?.runId,
            }
          : m
      )
    )
  }, [stream.status, stream.doneContent, stream.streamingText, stream.opinions, stream.calls, stream.doneIds])

  // 当前会话变化（选中历史 / 新建）时加载该 thread 的消息
  useEffect(() => {
    const tid = currentThreadId
    lastAssistantIdRef.current = null
    setMessages([])
    void restoreHistory(tid).then((restored) => {
      const msgs: ConsultMessage[] = restored.map((r) => {
        const calls = Array.isArray(r.metadata?.calls)
          ? (r.metadata.calls as ConsultCall[])
          : Array.isArray(r.raw?.consult_calls)
            ? (r.raw.consult_calls as ConsultCall[])
            : undefined
        const opinions = (r.metadata?.opinions && typeof r.metadata.opinions === "object")
          ? (r.metadata.opinions as Record<string, string>)
          : undefined
        return {
          id: nextId(),
          role: r.role,
          content: r.content,
          messageId: r.messageId,
          turnId: r.turnId,
          runId: r.runId,
          calls,
          opinions,
        }
      })
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
    setDismissedThreads((prev) => ({ ...prev, [currentThreadId]: true }))
    void sendQuestion(q, values)
  }

  const handleEdit = (text: string) => {
    setInput(text)
    requestAnimationFrame(() => composerRef.current?.focus())
  }

  const handleNew = () => {
    setMessages([])
    lastAssistantIdRef.current = null
    useThreadStore.getState().registerThread("consult")
  }

  const isLive = (m: ConsultMessage) => m.id === lastAssistantIdRef.current && !m.content

  return (
    <div className="flex h-full flex-col">
      <ConversationHeader
        parent="会诊"
        title={threadTitle ?? "新对话"}
        subtitle="总调度官自动调度顾问，综合给出建议"
        threadId={currentThreadId}
        onNew={handleNew}
        onSearch={() => composerRef.current?.focus()}
      />

      <div className="relative flex-1 overflow-hidden">
        <div ref={scrollRef} className="h-full overflow-y-auto">
          <div className="relative mx-auto w-full max-w-[928px] px-4 pb-[200px] pt-7 sm:px-6 md:pl-12">
            {messages.length === 0 && stream.status === "idle" ? (
              <EmptyState
                title="你的求职顾问团队已就位"
                description="输入问题，总调度官会自动选择合适的顾问并综合给你建议。"
                accent={<AgentDots colors={CONSULT_AGENTS.map((a) => a.color)} />}
              />
            ) : (
              <div className="flex flex-col gap-10">
                {turns.map((turn) => {
                  const asst = turn.assistant
                  return (
                    <TurnSection
                      key={turn.id}
                      turnId={turn.id}
                      userContent={turn.user.content ?? ""}
                      isUser={turn.user.role === "user"}
                      highlighted={highlightId === turn.id}
                      onEdit={handleEdit}
                    >
                      {asst && (isLive(asst) ? (
                        <LiveAssistant stream={stream} />
                      ) : (
                        <HistoryAssistant msg={asst} threadId={currentThreadId} onFeedback={() => showToast("感谢你的反馈")} />
                      ))}
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
            onSend={handleSend}
            disabled={stream.status === "streaming"}
            streaming={stream.status === "streaming"}
            onStop={() => stopStream(currentThreadId)}
            placeholder="输入需要会诊的问题…"
            hint="总调度官自动调度顾问，综合给出建议"
            toolbar
            textareaRef={composerRef}
            className="w-full"
          />
        </div>
        <ToastBubble message={toast} />
      </div>

      <ConsultFormDialog
        open={!!stream.pendingInput && stream.status !== "streaming" && !formDismissed}
        message={stream.pendingInput?.message}
        fields={stream.pendingInput?.fields ?? []}
        onClose={() => setDismissedThreads((prev) => ({ ...prev, [currentThreadId]: true }))}
        onSubmit={handleFormSubmit}
      />
    </div>
  )
}

function LiveAssistant({ stream }: { stream: StreamSession }) {
  const live = stream.status === "streaming"
  return (
    <div className="w-full space-y-3">
      {live && stream.stage === "consult" && (
        <p className="flex items-center gap-2 text-[11.5px] text-ink-faint">
          <span className="working-pulse h-1.5 w-1.5 rounded-full bg-ink-faint" />
          总调度官正在分析并调度顾问
        </p>
      )}
      {stream.dispatch && (
        <div className="flex flex-wrap items-center gap-1.5 text-[11.5px] text-ink-faint">
          <span>第 {stream.dispatch.round} 轮调度：</span>
          {stream.dispatch.agents.map((id) => {
            const meta = AGENT_META[id] ?? { label: id, color: "#78716C" }
            return (
              <span
                key={id}
                className="flex items-center gap-1.5 rounded-full border border-[var(--border-soft)] bg-surface-1 px-2.5 py-0.5"
              >
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: meta.color }} />
                {meta.label}
              </span>
            )
          })}
        </div>
      )}
      {(stream.stage === "synthesis" || stream.streamingText || stream.doneContent) && (
        <AgentPanel>
          <div className="mb-1.5 flex items-center gap-2">
            <Users className="h-3.5 w-3.5 text-ink-soft" strokeWidth={1.7} />
            <span className="text-[12.5px] font-medium text-ink">{ORCHESTRATOR_META.label}结论</span>
          </div>
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
        </AgentPanel>
      )}
    </div>
  )
}

function HistoryAssistant({ msg, threadId, onFeedback }: { msg: ConsultMessage; threadId: string; onFeedback?: (fb: MessageFeedback) => void }) {
  const opinions = msg.opinions ?? {}
  const calls = msg.calls ?? []
  const ids = Object.keys(opinions)
  const groups = calls.reduce<Record<number, ConsultCall[]>>((acc, call) => {
    // round 可能缺失（异常兜底只写 {content}）；缺省归入第 0 轮，渲染时再兜底文案。
    ;(acc[call.round ?? 0] ||= []).push(call)
    return acc
  }, {})
  return (
    <div className="w-full space-y-3">
      {Object.keys(groups).length > 0 && (
        <details className="group rounded-[8px] border border-[var(--border-soft)] bg-surface-2 px-3 py-2">
          <summary className="flex cursor-pointer items-center gap-1.5 text-[11.5px] font-medium text-ink-soft">
            <ChevronDown className="h-3.5 w-3.5 transition-transform duration-100 group-open:rotate-180" />
            查看调度过程（{calls.length} 次调用）
          </summary>
          <div className="mt-2 space-y-2">
            {Object.entries(groups).map(([round, roundCalls]) => (
              <div key={round} className="space-y-1.5">
                <p className="text-[11px] font-medium text-ink-faint">{round === "0" ? "调度过程" : `第 ${round} 轮`}</p>
                {roundCalls.map((call) => {
                  const meta = AGENT_META[call.agent] ?? { label: call.agent, color: "#78716C" }
                  return (
                    <div key={`${round}-${call.agent}`} className="rounded-[8px] bg-surface-1 p-2.5">
                      <div className="mb-1 flex items-center gap-1.5">
                        <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: meta.color }} />
                        <span className="text-[12px] font-medium" style={{ color: meta.color }}>{meta.label}</span>
                      </div>
                      {call.task && <p className="mb-1 text-[11px] text-ink-faint">{call.task}</p>}
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
        <details className="group rounded-[8px] border border-[var(--border-soft)] bg-surface-2 px-3 py-2">
          <summary className="flex cursor-pointer items-center gap-1.5 text-[11.5px] font-medium text-ink-soft">
            <ChevronDown className="h-3.5 w-3.5 transition-transform duration-100 group-open:rotate-180" />
            查看 {ids.length} 位顾问的独立意见
          </summary>
          <div className="mt-2 space-y-2">
            {ids.map((id) => {
              const meta = AGENT_META[id] ?? { label: id, color: "#78716C" }
              return (
                <div key={id} className="rounded-[8px] bg-surface-1 p-2.5">
                  <div className="mb-1 flex items-center gap-1.5">
                    <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: meta.color }} />
                    <span className="text-[12px] font-medium" style={{ color: meta.color }}>{meta.label}</span>
                  </div>
                  <MarkdownContent className="text-[13px]">{opinions[id]}</MarkdownContent>
                </div>
              )
            })}
          </div>
        </details>
      )}
      <AgentPanel>
        <div className="mb-1.5 flex items-center gap-2">
          <Users className="h-3.5 w-3.5 text-ink-soft" strokeWidth={1.7} />
          <span className="text-[12.5px] font-medium text-ink">{ORCHESTRATOR_META.label}结论</span>
        </div>
        <MarkdownContent>{msg.content || ""}</MarkdownContent>
      </AgentPanel>
      <FeedbackArea messageId={msg.messageId} threadId={threadId} content={msg.content || ""} onFeedback={onFeedback} />
    </div>
  )
}
