import { useEffect, useMemo, useRef, useState } from "react"
import { Plus, BookOpen, Check } from "lucide-react"
import { Button } from "@/components/ui/button"
import { PromptComposer } from "@/components/prompt/PromptComposer"
import { WorkspaceHeader } from "@/components/workspace/WorkspaceHeader"
import { EmptyState } from "@/components/workspace/EmptyState"
import { AssistantMessage } from "@/components/conversation/AssistantMessage"
import { ConversationRail } from "@/components/conversation/ConversationRail"
import { TurnSection } from "@/components/conversation/TurnSection"
import { ToastBubble } from "@/components/conversation/ToastBubble"
import { groupTurns } from "@/components/conversation/turn"
import { useConversationNavigation } from "@/hooks/useConversationNavigation"
import { useToast } from "@/hooks/useToast"
import { useChatScroll } from "@/hooks/useChatScroll"
import { JumpToLatest } from "@/components/JumpToLatest"
import { useThreadStore } from "@/store/threadStore"
import { IDLE_SESSION, useStreamStore } from "@/store/streamStore"
import { apiFetch } from "@/lib/auth"
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
  const currentThreadId = useThreadStore((s) => s.currentThreadByModule.interview)
  // 每会话独立流：切换会话不影响其他会话正在进行的回答
  const stream = useStreamStore((s) => s.sessions[currentThreadId] ?? IDLE_SESSION)
  const startStream = useStreamStore((s) => s.start)
  const stopStream = useStreamStore((s) => s.stop)
  const { scrollRef, showJumpToLatest, jumpToLatest } = useChatScroll([stream.streamingText, messages])
  const initializing = stream.status === "streaming" && stream.streamingText === "" && Object.keys(stream.agentChunks).length === 0
  /** 当前作答对应的题目（用户回答前最近一条面试官消息），done 评分后入 qaList */
  const pendingRef = useRef<{ q: string; a: string } | null>(null)

  // ── Turn 分组 + Anchor Rail 导航 ──
  const turns = useMemo(() => groupTurns(messages), [messages])
  const turnIds = useMemo(() => turns.map((t) => t.user.id), [turns])
  const { activeId, selectTurn, highlightId } = useConversationNavigation(turnIds, scrollRef)
  const { toast, showToast } = useToast()
  const composerRef = useRef<HTMLTextAreaElement | null>(null)

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
    pendingRef.current = null
    setMessages([])
    setQaList([])
    setTopic("")
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
    await startStream(currentThreadId, "/interview/chat", { topic: topicOverride ?? topic, messages: history, thread_id: currentThreadId })
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
    await apiFetch("/api/interview/record", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entries: qaList.map((qa) => ({ q: qa.question, a: qa.answer, score: qa.score })) }),
    })
    setQaList([])
  }

  const handleEdit = (text: string) => {
    setInput(text)
    requestAnimationFrame(() => composerRef.current?.focus())
  }

  const handleNew = () => {
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
      <WorkspaceHeader
        title="面试练习"
        subtitle="对话式模拟面试 · 出题 → 作答 → 评分 → 追问"
        actions={
          <>
            {messages.length > 0 && (
              <Button variant="outline" size="sm" onClick={handleEnd} disabled={lastIsStreaming}>
                结束面试
              </Button>
            )}
            {qaList.length > 0 && (
              <Button variant="outline" size="sm" onClick={handleRecord}>
                <Check className="mr-1 h-3.5 w-3.5" strokeWidth={1.7} />保存 {qaList.length} 条到记忆
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={handleNew}>
              <Plus className="mr-1 h-3.5 w-3.5" strokeWidth={1.7} />新面试
            </Button>
          </>
        }
      />

      <div className="relative flex-1 overflow-hidden">
        <div ref={scrollRef} className="h-full overflow-y-auto">
          <div className="relative mx-auto w-full max-w-[928px] px-4 pb-[200px] pt-7 sm:px-6 md:pl-12">
            {messages.length === 0 ? (
              <EmptyState
                title="开始一轮对话式模拟面试"
                description={
                  <>
                    输入您的薄弱知识点，面试官一次只问一题，
                    <br />
                    作答后自动评分、给出黄金回答范例并继续追问。
                  </>
                }
                accent={
                  <span
                    className="flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11.5px] font-medium"
                    style={{ color: INTERVIEWER.color, borderColor: `${INTERVIEWER.color}40`, backgroundColor: `${INTERVIEWER.color}10` }}
                  >
                    <BookOpen className="h-3.5 w-3.5" strokeWidth={1.7} /> 面试官已就位
                  </span>
                }
              >
                <div className="mt-6 text-left">
                  <PromptComposer
                    value={input}
                    onChange={setInput}
                    onSend={() => startWithTopic(input)}
                    placeholder="输入您的薄弱知识点，留空则随机出题…"
                    sendLabel="开始面试"
                    allowEmptySend
                  />
                </div>
              </EmptyState>
            ) : (
              <div className="flex flex-col gap-10">
                {turns.map((turn, i) => {
                  const isLast = i === turns.length - 1
                  const asst = turn.assistant
                  const asstStreaming = Boolean(asst?.streaming) && lastIsStreaming && isLast
                  const content = asstStreaming ? stream.streamingText : (asst?.content ?? "")
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
                        <AssistantMessage
                          messageId={asst.id}
                          content={content}
                          label={INTERVIEWER.label}
                          color={INTERVIEWER.color}
                          streaming={asstStreaming}
                          thinking={stream.thinking}
                          initializing={asstStreaming && initializing}
                          initText="面试官正在思考题目"
                          workingText="正在生成反馈…"
                          onFeedback={() => showToast("感谢你的反馈")}
                        />
                      )}
                    </TurnSection>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        <ConversationRail turns={turns} activeTurnId={activeId} onSelect={selectTurn} />
        <div className="composer-fade pointer-events-none absolute inset-x-0 bottom-0 z-10 h-[150px]" />
        <JumpToLatest visible={showJumpToLatest} onClick={jumpToLatest} className="bottom-[110px]" />
        {messages.length > 0 && (
          <div className="absolute inset-x-0 bottom-0 z-20 flex justify-center px-3 pb-3 sm:px-6 sm:pb-4">
            <PromptComposer
              value={input}
              onChange={setInput}
              onSend={() => send(input)}
              disabled={lastIsStreaming}
              streaming={lastIsStreaming}
              onStop={() => stopStream(currentThreadId)}
              placeholder="作答，或输入「结束面试」获取总结…"
              hint="面试官一轮一问，回答后自动评分并追问"
              textareaRef={composerRef}
              className="w-full"
            />
          </div>
        )}
        <ToastBubble message={toast} />
      </div>
    </div>
  )
}
