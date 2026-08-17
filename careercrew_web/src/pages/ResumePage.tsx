import { useEffect, useMemo, useRef, useState, type DragEvent } from "react"
import { FileText, X } from "lucide-react"
import { PromptComposer } from "@/components/prompt/PromptComposer"
import { Tooltip } from "@/components/ui/tooltip"
import { EmptyState, AgentDots } from "@/components/workspace/EmptyState"
import { JumpToLatest } from "@/components/JumpToLatest"
import ResumePanel from "@/components/ResumePanel"
import { AssistantMessage } from "@/components/conversation/AssistantMessage"
import { VersionSwitcher } from "@/components/conversation/VersionSwitcher"
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
import { useThreadStore } from "@/store/threadStore"
import { IDLE_SESSION, useStreamStore } from "@/store/streamStore"
import { AGENT_META } from "@/types"
import { cn } from "@/lib/utils"
import { pollResumeUpload, type ActiveResume } from "@/lib/resumeUpload"
import { restoreHistory } from "@/lib/historyRestore"
import { apiFetch } from "@/lib/auth"
import { apiErrorText, networkErrorText } from "@/lib/errors"

let msgId = 0
const nextId = () => `msg-${++msgId}`

const RESUME_ADVISOR = AGENT_META.resume_advisor

interface ChatMsg {
  id: string
  role: "user" | "assistant"
  content: string
  streaming?: boolean
  messageId?: string
  turnId?: string
  runId?: string
}

export default function ResumePage() {
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState("")
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [panelOpen, setPanelOpen] = useState(false)
  /** 当前会话待使用的简历（展示在输入框上方，可移除）；首轮发送时随请求携带 */
  const [activeResume, setActiveResume] = useState<ActiveResume | null>(null)
  /** 最近上传/选中的简历：首轮发送时随请求携带，之后由后端按线程存储复用 */
  const pendingResumeRef = useRef<{ threadId: string; text: string } | null>(null)
  const currentThreadId = useThreadStore((s) => s.currentThreadByModule.resume)
  // 会话标题：首条消息后由 touchThread 落库，展示在 Header 左侧
  const threadTitle = useThreadStore((s) =>
    s.threadsByModule.resume?.find((t) => t.thread_id === s.currentThreadByModule.resume)?.title
  )
  // 每会话独立流：切换会话不影响其他会话正在进行的回答
  const stream = useStreamStore((s) => s.sessions[currentThreadId] ?? IDLE_SESSION)
  const startStream = useStreamStore((s) => s.start)
  const regenerateStream = useStreamStore((s) => s.regenerate)
  const stopStream = useStreamStore((s) => s.stop)
  const { scrollRef, showJumpToLatest, jumpToLatest } = useChatScroll([stream.streamingText, messages])
  const initializing = stream.status === "streaming" && stream.streamingText === "" && Object.keys(stream.agentChunks).length === 0

  // ── Turn 分组 + Anchor Rail 导航 ──
  const turns = useMemo(() => groupTurns(messages), [messages])
  const turnIds = useMemo(() => turns.map((t) => t.user.id), [turns])
  const { activeId, selectTurn, highlightId } = useConversationNavigation(turnIds, scrollRef)
  const { toast, showToast } = useToast()
  const [versionSelections, setVersionSelections] = useState<Record<string, number>>({})
  const composerRef = useRef<HTMLTextAreaElement | null>(null)
  const workspaceRef = useRef<HTMLDivElement | null>(null)
  const search = useConversationSearch(messages, scrollRef, workspaceRef)

  // 流结束：把最终内容写回最后一条 assistant 气泡
  useEffect(() => {
    if (stream.status !== "done" || !stream.doneContent) return
    setMessages((prev) => prev.map((m, i) =>
      i === prev.length - 1 && (m.streaming ?? false)
        ? {
            ...m,
            content: stream.doneContent,
            streaming: false,
            messageId: stream.doneIds?.messageId,
            turnId: stream.doneIds?.turnId,
            runId: stream.doneIds?.runId,
          }
        : m,
    ))
  }, [stream.status, stream.doneContent, stream.doneIds])

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
    setVersionSelections({})
    pendingResumeRef.current = null
    setActiveResume(null)
    setMessages([])
    void restoreHistory(tid).then((restored) => {
      const msgs: ChatMsg[] = restored.map((r) => ({
        id: nextId(),
        role: r.role,
        content: r.content,
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

  /** 把一份简历设为当前会话使用的简历（展示在输入框上方，首轮发送时随请求携带）。 */
  const activateResume = (resume: ActiveResume) => {
    pendingResumeRef.current = { threadId: currentThreadId, text: resume.content }
    setActiveResume(resume)
  }

  /** 移除当前会话的简历（不再随首轮发送携带）。 */
  const removeActiveResume = () => {
    pendingResumeRef.current = null
    setActiveResume(null)
  }

  const handleUpload = async (file: File) => {
    if (uploading) return
    setUploading(true)
    try {
      const form = new FormData()
      form.append("file", file)
      const resp = await apiFetch("/api/resume/upload", { method: "POST", body: form })
      if (!resp.ok) {
        const errText = await apiErrorText(resp, "上传失败，请重试")
        setMessages((prev) => [...prev, { id: nextId(), role: "user", content: `上传失败：${errText}` }])
        return
      }
      const data = await resp.json()
      const job = await pollResumeUpload(data.job_id)
      if (job.status === "error") {
        setMessages((prev) => [...prev, { id: nextId(), role: "user", content: `解析失败：${job.error || "请重试"}` }])
        return
      }
      const r = job.result
      if (r) {
        activateResume({
          resume_id: r.resume_id,
          filename: r.filename,
          doc_type: r.doc_type,
          char_count: r.char_count,
          content: r.content,
        })
      }
    } catch (e) {
      setMessages((prev) => [...prev, { id: nextId(), role: "user", content: `上传失败：${networkErrorText(e, "网络连接失败，请重试")}` }])
    } finally {
      setUploading(false)
    }
  }

  const handleDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleUpload(file)
  }

  const send = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || stream.status === "streaming") return
    const isFirst = messages.length === 0
    const pending = pendingResumeRef.current
    const resumeText = pending && pending.threadId === currentThreadId ? pending.text : ""
    if (pending && pending.threadId === currentThreadId) {
      pendingResumeRef.current = null
      setActiveResume(null)
    }
    setMessages((prev) => [...prev, { id: nextId(), role: "user", content: trimmed }])
    setMessages((prev) => [...prev, { id: nextId(), role: "assistant", content: "", streaming: true }])
    setInput("")
    jumpToLatest()
    if (isFirst) useThreadStore.getState().touchThread("resume", currentThreadId, trimmed)
    await startStream(currentThreadId, "/resume/chat", { question: trimmed, resume_text: resumeText, thread_id: currentThreadId })
  }

  /** 重新生成保留旧版本；稳定 ID 走后端 regenerate，遗留无 ID 消息保留兼容重发。 */
  const handleRegenerate = async (turnId: string, messageId?: string) => {
    if (stream.status === "streaming") return
    const turn = groupTurns(messages).find((t) => t.id === turnId)
    if (!turn?.assistant || !turn.user.content) return
    setMessages((prev) => [...prev, { id: nextId(), role: "assistant", content: "", streaming: true }])
    jumpToLatest()
    if (messageId) await regenerateStream(currentThreadId, messageId)
    else await startStream(currentThreadId, "/resume/chat", {
      question: turn.user.content, resume_text: "", thread_id: currentThreadId,
    })
  }

  const handleEdit = (text: string) => {
    setInput(text)
    requestAnimationFrame(() => composerRef.current?.focus())
  }

  const handleNew = () => {
    pendingResumeRef.current = null
    setActiveResume(null)
    setMessages([])
    setInput("")
    useThreadStore.getState().registerThread("resume")
  }

  const lastIsStreaming = stream.status === "streaming"

  return (
    <div className="flex h-full flex-col">
      <ConversationHeader
        parent="简历优化"
        title={threadTitle ?? "新对话"}
        subtitle="上传简历，对话式定制优化 · 按目标 JD 重构"
        threadId={currentThreadId}
        onNew={handleNew}
        onSearch={search.openSearch}
extra={
          <>
            <HeaderIconAction label="简历面板" onClick={() => setPanelOpen((v) => !v)}>
              <FileText className="h-4 w-4" strokeWidth={1.7} />
            </HeaderIconAction>
            <ConversationMenu
              threadId={currentThreadId}
              title={threadTitle ?? "新对话"}
              module="resume"
              onAfterClear={() => void restoreHistory(currentThreadId)}
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
        <div
          ref={scrollRef}
          className={cn("h-full overflow-y-auto", dragOver && "bg-surface-1")}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
        >
          <div className="relative mx-auto w-full max-w-[928px] px-4 pb-[200px] pt-7 sm:px-6 md:pl-12">
            {messages.length === 0 ? (
              <EmptyState
                title="上传简历，开始对话式优化"
                description={
                  <>
                    点击右上角「简历管理」；
                    <br />
                    随后直接在对话里描述目标 JD 或想优化的部分。
                  </>
                }
                accent={<AgentDots colors={["#D97706", "#0D9488", "#BE185D", "#7C3AED", "#2563EB"]} />}
              />
            ) : (
              <div className="flex flex-col gap-10">
                {turns.map((turn, i) => {
                  const isLast = i === turns.length - 1
                  const versions = turn.versions ?? (turn.assistant ? [turn.assistant] : [])
                  const selectedVersion = Math.min(versionSelections[turn.id] ?? versions.length - 1, versions.length - 1)
                  const asst = versions[selectedVersion]
                  const isNewestVersion = selectedVersion === versions.length - 1
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
                          stableMessageId={asst.messageId}
                          threadId={currentThreadId}
                          content={content}
                          label={RESUME_ADVISOR.label}
                          color={RESUME_ADVISOR.color}
                          streaming={asstStreaming}
                          completed={!asstStreaming}
                          thinking={stream.thinking}
                          initializing={asstStreaming && initializing}
                          initText="简历顾问正在分析"
                          workingText="正在优化简历…"
                          versionSwitcher={<VersionSwitcher
                            index={selectedVersion + 1}
                            total={versions.length}
                            onPrev={() => setVersionSelections((prev) => ({ ...prev, [turn.id]: Math.max(0, selectedVersion - 1) }))}
                            onNext={() => setVersionSelections((prev) => ({ ...prev, [turn.id]: Math.min(versions.length - 1, selectedVersion + 1) }))}
                          />}
                          onRegenerate={
                            isLast && isNewestVersion && !asstStreaming && Boolean(asst.content) && Boolean(turn.user.content)
                              ? () => handleRegenerate(turn.id, asst.messageId)
                              : undefined
                          }
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
            onSend={() => send(input)}
            disabled={stream.status === "streaming"}
            streaming={stream.status === "streaming"}
            onStop={() => stopStream(currentThreadId)}
            placeholder={activeResume ? "已添加简历，输入目标 JD 或想优化的部分…" : "上传简历，或直接输入简历内容与优化需求…"}
            hint="上传简历后，直接描述目标 JD 或想优化的部分"
            toolbar
            textareaRef={composerRef}
            className="w-full"
            header={
              activeResume ? (
                <div className="mb-2 flex justify-start">
                  <div className="flex items-center gap-2.5 rounded-[8px] border border-[var(--border-soft)] bg-surface-1 py-1.5 pl-3 pr-1.5">
                    <FileText className="h-4 w-4 shrink-0 text-primary" strokeWidth={1.7} />
                    <div className="min-w-0">
                      <p className="max-w-[220px] truncate text-[12px] font-medium text-ink">{activeResume.filename}</p>
                      <p className="text-[10.5px] text-ink-faint">{activeResume.doc_type} · {activeResume.char_count} 字符</p>
                    </div>
                    <Tooltip label="移除简历">
                      <button
                        className="rounded-[5px] p-1 text-ink-faint transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
                        onClick={removeActiveResume}
                        aria-label="移除简历"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </Tooltip>
                  </div>
                </div>
              ) : undefined
            }
          />
        </div>
        <ToastBubble message={toast} />

        {/* 右上角简历管理抽屉 */}
        {panelOpen && (
          <aside className="absolute inset-y-0 right-0 z-20 w-[400px] overflow-y-auto border-l border-[var(--border-soft)] bg-workspace p-4">
            <ResumePanel onClose={() => setPanelOpen(false)} onActive={activateResume} />
          </aside>
        )}
      </div>
    </div>
  )
}
