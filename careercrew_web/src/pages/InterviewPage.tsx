import { useEffect, useMemo, useRef, useState } from "react"
import { Flag, Check } from "lucide-react"
import { PromptComposer } from "@/components/prompt/PromptComposer"
import { AttachmentPicker, type AttachmentPickerHandle } from "@/components/prompt/AttachmentPicker"
import { toMessageAttachments, type Attachment } from "@/lib/attachments"
import { EmptyState, AgentDots } from "@/components/workspace/EmptyState"
import { AssistantMessage } from "@/components/conversation/AssistantMessage"
import { ConversationRail } from "@/components/conversation/ConversationRail"
import { ConversationHeader, HeaderIconAction } from "@/components/conversation/ConversationHeader"
import { ConversationMenu } from "@/components/conversation/ConversationMenu"
import { ConversationSearchBar } from "@/components/conversation/ConversationSearch"
import { useConversationSearch } from "@/components/conversation/useConversationSearch"
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
import { apiErrorText, networkErrorText } from "@/lib/errors"
import { restoreHistory } from "@/lib/historyRestore"
import type { InterviewQA, MessageAttachment } from "@/types"

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
  messageId?: string
  turnId?: string
  runId?: string
  attachments?: MessageAttachment[]
}

export default function InterviewPage() {
  const [topic, setTopic] = useState("")
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState("")
  const attachRef = useRef<AttachmentPickerHandle>(null)
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [qaList, setQaList] = useState<InterviewQA[]>([])
  const currentThreadId = useThreadStore((s) => s.currentThreadByModule.interview)
  // 会话标题：首条消息后由 touchThread 落库，展示在 Header 左侧
  const threadTitle = useThreadStore((s) =>
    s.threadsByModule.interview?.find((t) => t.thread_id === s.currentThreadByModule.interview)?.title
  )
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
  const workspaceRef = useRef<HTMLDivElement | null>(null)
  const search = useConversationSearch(messages, scrollRef, workspaceRef)

  // 流结束：把最终内容写回最后一条 assistant 气泡；若带评分则计入 qaList
  useEffect(() => {
    if (stream.status !== "done" || !stream.doneContent) return
    const pending = pendingRef.current
    pendingRef.current = null
    const patch: Partial<ChatMsg> = {
      content: stream.doneContent,
      streaming: false,
      messageId: stream.doneIds?.messageId,
      turnId: stream.doneIds?.turnId,
      runId: stream.doneIds?.runId,
    }
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
  }, [stream.status, stream.doneContent, stream.doneIds, stream.doneScore, stream.doneFeedback])

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
    void restoreHistory(tid).then((restored) => {
      const msgs: ChatMsg[] = restored.map((r) => ({
        id: nextId(),
        role: r.role,
        content: r.content,
        attachments: r.attachments,
        messageId: r.messageId,
        turnId: r.turnId,
        runId: r.runId,
      }))
      // 切回一个仍在流式回答的会话：补一个流式占位气泡
      const live = useStreamStore.getState().sessions[tid]
      setMessages(live && live.status === "streaming"
        ? [...msgs, { id: nextId(), role: "assistant", content: "", streaming: true }]
        : msgs)
      jumpToLatest()
    })
  }, [currentThreadId, jumpToLatest])

  const send = async (text: string, topicOverride?: string) => {
    const trimmed = text.trim()
    if (!trimmed || stream.status === "streaming") return
    const isFirst = messages.length === 0
    const turnAttachments = attachments
    const prev = messages[messages.length - 1]
    pendingRef.current = prev?.role === "assistant" && prev.content
      ? { q: prev.content, a: trimmed }
      : null
    setMessages((prev) => [...prev, {
      id: nextId(),
      role: "user",
      content: trimmed,
      attachments: toMessageAttachments(turnAttachments),
    }])
    setMessages((prev) => [...prev, { id: nextId(), role: "assistant", content: "", streaming: true }])
    setInput("")
    jumpToLatest()
    if (isFirst) useThreadStore.getState().touchThread("interview", currentThreadId, topicOverride || text)
    const history = [...messages, { role: "user", content: trimmed }].map((m) => ({
      role: m.role,
      content: m.content,
    }))
    const body: Record<string, unknown> = {
      topic: topicOverride ?? topic, messages: history, thread_id: currentThreadId,
    }
    if (turnAttachments.length) body.attachments = turnAttachments.map((a) => ({ id: a.id }))
    attachRef.current?.clear()
    await startStream(currentThreadId, "/interview/chat", body)
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
    try {
      const resp = await apiFetch("/api/interview/record", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entries: qaList.map((qa) => ({ q: qa.question, a: qa.answer, score: qa.score })) }),
      })
      if (!resp.ok) {
        showToast(await apiErrorText(resp, "保存到记忆失败，请重试"))
        return
      }
      setQaList([])
      showToast(`已保存 ${qaList.length} 条问答到记忆`)
    } catch (e) {
      showToast(networkErrorText(e, "保存失败，请检查网络后重试"))
    }
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
      <ConversationHeader
        parent="面试练习"
        title={threadTitle ?? "新面试"}
        subtitle="对话式模拟面试 · 出题 → 作答 → 评分 → 追问"
        threadId={currentThreadId}
        onNew={handleNew}
        onSearch={search.openSearch}
        extra={
          <>
            {qaList.length > 0 && (
              <HeaderIconAction label={`保存 ${qaList.length} 条到记忆`} onClick={() => void handleRecord()}>
                <Check className="h-4 w-4" strokeWidth={1.7} />
              </HeaderIconAction>
            )}
            {messages.length > 0 ? (
              <HeaderIconAction label="结束面试" onClick={handleEnd} disabled={lastIsStreaming}>
                <Flag className="h-4 w-4" strokeWidth={1.7} />
              </HeaderIconAction>
            ) : undefined}
            <ConversationMenu
              threadId={currentThreadId}
              title={threadTitle ?? "新对话"}
              module="interview"
              onAfterClear={() => setMessages([])}
            />
          </>
        }
      />

      <div
        ref={workspaceRef}
        onMouseEnter={search.workspaceHoverHandlers.onMouseEnter}
        onMouseLeave={search.workspaceHoverHandlers.onMouseLeave}
        className="relative flex-1 overflow-hidden"
      >
        <ConversationSearchBar
          open={search.open}
          keyword={search.keyword}
          currentIndex={search.currentIndex}
          total={search.total}
          onKeyword={search.setKeyword}
          onPrev={search.prev}
          onNext={search.next}
          onClose={search.close}
        />
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
                accent={<AgentDots colors={["#BE185D", "#0D9488", "#D97706", "#7C3AED", "#2563EB"]} />}
              />
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
                      userAttachments={turn.user.attachments}
                      isUser={turn.user.role === "user"}
                      highlighted={highlightId === turn.id}
                      onEdit={handleEdit}
                    >
                      {asst && (
                        <AssistantMessage
                          messageId={asst.id}
                          stableMessageId={asst.messageId}
                          threadId={currentThreadId}
                          content={content}
                          label={INTERVIEWER.label}
                          color={INTERVIEWER.color}
                          streaming={asstStreaming}
                          completed={!asstStreaming && Boolean(asst.messageId)}
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
        <div className="absolute inset-x-0 bottom-0 z-20 flex justify-center px-3 pb-3 sm:px-6 sm:pb-4">
          <PromptComposer
            value={input}
            onChange={setInput}
            onSend={() => (messages.length === 0 ? startWithTopic(input) : send(input))}
            disabled={lastIsStreaming}
            streaming={lastIsStreaming}
            onStop={() => stopStream(currentThreadId)}
            placeholder={
              messages.length === 0
                ? "输入您的薄弱知识点，留空则随机出题…"
                : "作答，或输入「结束面试」获取总结…"
            }
            allowEmptySend
            toolbar
            onAddAttachment={() => attachRef.current?.pick()}
            attachments={<AttachmentPicker ref={attachRef} embedded threadId={currentThreadId} disabled={lastIsStreaming} onAttachmentsChange={setAttachments} />}
            textareaRef={composerRef}
            className="w-full"
          />
        </div>
        <ToastBubble message={toast} />
      </div>
    </div>
  )
}
