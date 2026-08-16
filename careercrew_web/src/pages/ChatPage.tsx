import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { MoreHorizontal, Search, SquarePen } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { PromptComposer } from "@/components/prompt/PromptComposer"
import { WorkspaceHeader } from "@/components/workspace/WorkspaceHeader"
import { EmptyState, AgentDots } from "@/components/workspace/EmptyState"
import { UserMessage } from "@/components/conversation/UserMessage"
import { AssistantMessage } from "@/components/conversation/AssistantMessage"
import { VersionSwitcher } from "@/components/conversation/VersionSwitcher"
import { ConversationRail } from "@/components/conversation/ConversationRail"
import { Tooltip } from "@/components/ui/tooltip"
import { groupTurns, turnAnchorId } from "@/components/conversation/turn"
import { useActiveTurn } from "@/hooks/useActiveTurn"
import { useChatScroll } from "@/hooks/useChatScroll"
import { JumpToLatest } from "@/components/JumpToLatest"
import { useChatStore } from "@/store/chatStore"
import { useThreadStore } from "@/store/threadStore"
import { IDLE_SESSION, useStreamStore } from "@/store/streamStore"
import { restoreHistory } from "@/lib/historyRestore"
import { AGENT_META } from "@/types"
import type { ChatMessage } from "@/types"

let msgId = 0
const nextId = () => `msg-${++msgId}`

export default function ChatPage() {
  const [input, setInput] = useState("")
  const {
    messages, addMessage, updateLastAssistant, removeLastEmptyAssistant,
    newConversation,
    bumpProfileNonce,
  } = useChatStore()
  const currentThreadId = useThreadStore((s) => s.currentThreadByModule.chat)
  // 会话标题：首条消息后由 touchThread 落库，展示在 Header 左侧
  const threadTitle = useThreadStore((s) =>
    s.threadsByModule.chat?.find((t) => t.thread_id === s.currentThreadByModule.chat)?.title
  )
  // 每会话独立流：切换会话不影响其他会话正在进行的回答
  const stream = useStreamStore((s) => s.sessions[currentThreadId] ?? IDLE_SESSION)
  const startStream = useStreamStore((s) => s.start)
  const regenerateStream = useStreamStore((s) => s.regenerate)
  const stopStream = useStreamStore((s) => s.stop)
  const { scrollRef, showJumpToLatest, jumpToLatest } = useChatScroll([stream.streamingText, messages])
  const initializing = stream.status === "streaming" && stream.streamingText === "" && Object.keys(stream.agentChunks).length === 0

  // ── Turn 分组 + Anchor Rail 激活态 ──
  const turns = useMemo(() => groupTurns(messages), [messages])
  const turnIds = useMemo(() => turns.map((t) => t.user.id), [turns])
  const { activeId, select: selectTurn } = useActiveTurn(turnIds, scrollRef)

  const [highlightId, setHighlightId] = useState<string | null>(null)
  const [versionSelections, setVersionSelections] = useState<Record<string, number>>({})
  const [toast, setToast] = useState<string | null>(null)
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const composerRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(
    () => () => {
      if (highlightTimer.current) clearTimeout(highlightTimer.current)
      if (toastTimer.current) clearTimeout(toastTimer.current)
    },
    []
  )

  const showToast = (text: string) => {
    setToast(text)
    if (toastTimer.current) clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(null), 2000)
  }

  useEffect(() => {
    if (stream.status === "error") {
      // 流出错：移除未填充的空助手占位气泡
      removeLastEmptyAssistant()
      return
    }
    if (stream.status === "done" && stream.doneContent) {
      updateLastAssistant(stream.doneContent, stream.doneIds ?? undefined)
      if (stream.stage === "match") useChatStore.getState().setLastMatchResult(stream.doneContent)
      bumpProfileNonce()
    }
  }, [stream.status, stream.doneContent, stream.doneIds, updateLastAssistant, removeLastEmptyAssistant, stream.stage, bumpProfileNonce])

  // 当前会话变化（侧边栏选中历史 / 新建会话）时加载该 thread 的消息
  useEffect(() => {
    const tid = currentThreadId
    setVersionSelections({})
    useChatStore.setState({ messages: [], threadId: tid })
    void restoreHistory(tid).then((restored) => {
      const msgs: ChatMessage[] = restored.map((r) => ({
        id: nextId(),
        role: r.role,
        content: r.content,
        agent: r.role === "assistant" ? "career_planner" : undefined,
        messageId: r.messageId,
        turnId: r.turnId,
        runId: r.runId,
      }))
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

  /** Rail 横条点击：锁定激活态并滚动到对应 Turn，短暂高亮用户气泡 */
  const handleSelectTurn = (turnId: string) => {
    selectTurn(turnId)
    const el = document.getElementById(turnAnchorId(turnId))
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ behavior: "smooth", block: "start" })
    }
    setHighlightId(turnId)
    if (highlightTimer.current) clearTimeout(highlightTimer.current)
    highlightTimer.current = setTimeout(() => setHighlightId(null), 900)
  }

  /** 编辑用户消息：回填输入框并聚焦（不产生新消息） */
  const handleEdit = (text: string) => {
    setInput(text)
    requestAnimationFrame(() => composerRef.current?.focus())
  }

  /** 重新生成保留旧版本；稳定 ID 走后端 regenerate，遗留无 ID 消息保留兼容重发。 */
  const handleRegenerate = async (turnId: string, messageId?: string) => {
    if (stream.status === "streaming") return
    const st = useChatStore.getState()
    const turn = groupTurns(st.messages).find((t) => t.id === turnId)
    if (!turn?.assistant) return
    addMessage({ id: nextId(), role: "assistant", content: "", agent: "career_planner", streaming: true })
    jumpToLatest()
    if (messageId) await regenerateStream(currentThreadId, messageId)
    else await startStream(currentThreadId, "/chat/plan", { intent: turn.user.content, thread_id: currentThreadId })
  }

  const lastIsStreaming = stream.status === "streaming"

  return (
    <div className="flex h-full flex-col">
      <WorkspaceHeader
        parent="求职规划"
        title={threadTitle ?? "新对话"}
        subtitle="职业规划师 · 求职规划"
        actions={
          <div className="flex items-center gap-0.5">
            <HeaderIconButton title="新对话" onClick={handleNew}>
              <SquarePen className="h-4 w-4" strokeWidth={1.7} />
            </HeaderIconButton>
            <HeaderIconButton title="搜索" onClick={() => composerRef.current?.focus()}>
              <Search className="h-4 w-4" strokeWidth={1.7} />
            </HeaderIconButton>
            <HeaderIconButton
              title="复制会话 ID"
              onClick={() => void useThreadStore.getState().copyThreadId(currentThreadId)}
            >
              <MoreHorizontal className="h-4 w-4" strokeWidth={1.7} />
            </HeaderIconButton>
          </div>
        }
      />

      {/* Conversation Area：滚动线程 + 左侧 Minimap Rail + 浮动 Composer（渐变收底） */}
      <div className="relative flex-1 overflow-hidden">
        <div ref={scrollRef} className="h-full overflow-y-auto">
          <div className="relative mx-auto w-full max-w-[928px] px-4 pb-[200px] pt-7 sm:px-6 md:pl-12">
            {messages.length === 0 ? (
              <EmptyState
                title="你的求职顾问团队已就位"
                description={
                  <>
                    告诉规划师你的方向和背景，
                    <br />
                    帮你建立能力画像、确定目标公司、制定阶段规划。
                  </>
                }
                accent={<AgentDots colors={["#0D9488", "#D97706", "#BE185D", "#7C3AED", "#2563EB"]} />}
              >
                <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => {
                        setInput(s)
                        composerRef.current?.focus()
                      }}
                      className="rounded-full border border-[var(--border-soft)] px-3 py-1 text-[12px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </EmptyState>
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
                  const meta = asst?.agent ? AGENT_META[asst.agent] : undefined
                  return (
                    <section key={turn.id} id={turnAnchorId(turn.id)} className="relative scroll-mt-24">
                      {turn.user.role === "user" && (
                        <UserMessage
                          content={turn.user.content}
                          turnId={turn.id}
                          highlighted={highlightId === turn.id}
                          onEdit={handleEdit}
                        />
                      )}
                      {asst && (
                        <div className="mt-4">
                          <AssistantMessage
                            messageId={asst.id}
                            stableMessageId={asst.messageId}
                            threadId={currentThreadId}
                            content={content}
                            label={meta?.label ?? "顾问"}
                            color={meta?.color}
                            streaming={asstStreaming}
                            completed={!asstStreaming}
                            thinking={stream.thinking}
                            initializing={asstStreaming && initializing}
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
                        </div>
                      )}
                    </section>
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

        {/* 左侧 Minimap Rail（最左居中，横条导航） */}
        <ConversationRail turns={turns} activeTurnId={activeId} onSelect={handleSelectTurn} />

        {/* Composer 渐变收底 + 浮动输入框 */}
        <div className="composer-fade pointer-events-none absolute inset-x-0 bottom-0 z-10 h-[150px]" />
        <JumpToLatest visible={showJumpToLatest} onClick={jumpToLatest} className="bottom-[110px]" />
        <div className="absolute inset-x-0 bottom-0 z-20 flex justify-center px-3 pb-3 sm:px-6 sm:pb-4">
          <PromptComposer
            value={input}
            onChange={setInput}
            onSend={handleSend}
            disabled={lastIsStreaming}
            streaming={lastIsStreaming}
            onStop={() => stopStream(currentThreadId)}
            placeholder="Message Agent…（Enter 发送，Shift + Enter 换行）"
            toolbar
            textareaRef={composerRef}
            className="w-full"
          />
        </div>

        {toast && (
          <div className="absolute bottom-[130px] left-1/2 z-30 -translate-x-1/2 rounded-full border border-[var(--border-soft)] bg-workspace px-3 py-1.5 text-[12px] text-ink shadow-popover">
            {toast}
          </div>
        )}
      </div>
    </div>
  )
}

function HeaderIconButton({ title, onClick, children }: {
  title: string
  onClick: () => void
  children: ReactNode
}) {
  return (
    <Tooltip label={title} side="bottom">
      <button
        type="button"
        onClick={onClick}
        aria-label={title}
        className="flex h-[30px] w-[30px] items-center justify-center rounded-[7px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
      >
        {children}
      </button>
    </Tooltip>
  )
}
