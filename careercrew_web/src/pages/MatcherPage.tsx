import { useEffect, useMemo, useRef, useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { PromptComposer } from "@/components/prompt/PromptComposer"
import { EmptyState, AgentDots } from "@/components/workspace/EmptyState"
import { AssistantMessage } from "@/components/conversation/AssistantMessage"
import { VersionSwitcher } from "@/components/conversation/VersionSwitcher"
import { ConversationRail } from "@/components/conversation/ConversationRail"
import { ConversationHeader } from "@/components/conversation/ConversationHeader"
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
import { AGENT_META } from "@/types"
import { restoreHistory } from "@/lib/historyRestore"

interface MatcherMessage {
  id: string
  role: "user" | "assistant"
  content: string
  streaming?: boolean
  messageId?: string
  turnId?: string
  runId?: string
}

let msgId = 0
const nextId = () => `match-msg-${++msgId}`

export default function MatcherPage() {
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<MatcherMessage[]>([])
  const currentThreadId = useThreadStore((s) => s.currentThreadByModule.matcher)
  // 会话标题：首条消息后由 touchThread 落库，展示在 Header 左侧
  const threadTitle = useThreadStore((s) =>
    s.threadsByModule.matcher?.find((t) => t.thread_id === s.currentThreadByModule.matcher)?.title
  )
  // 每会话独立流：切换会话不影响其他会话正在进行的回答
  const stream = useStreamStore((s) => s.sessions[currentThreadId] ?? IDLE_SESSION)
  const startStream = useStreamStore((s) => s.start)
  const regenerateStream = useStreamStore((s) => s.regenerate)
  const stopStream = useStreamStore((s) => s.stop)
  const { scrollRef, showJumpToLatest, jumpToLatest } = useChatScroll([stream.streamingText, messages])
  const initializing = stream.status === "streaming" && stream.streamingText === "" && Object.keys(stream.agentChunks).length === 0
  const meta = AGENT_META.job_matcher

  // ── Turn 分组 + Anchor Rail 导航 ──
  const turns = useMemo(() => groupTurns(messages), [messages])
  const turnIds = useMemo(() => turns.map((t) => t.user.id), [turns])
  const { activeId, selectTurn, highlightId } = useConversationNavigation(turnIds, scrollRef)
  const { toast, showToast } = useToast()
  const [versionSelections, setVersionSelections] = useState<Record<string, number>>({})
  const composerRef = useRef<HTMLTextAreaElement | null>(null)
  const workspaceRef = useRef<HTMLDivElement | null>(null)
  const search = useConversationSearch(messages, scrollRef, workspaceRef)

  useEffect(() => {
    if (stream.status === "error") {
      // 流出错：移除未填充的空助手占位气泡
      setMessages((prev) =>
        prev.filter((m) => !(m.role === "assistant" && m.streaming && !m.content))
      )
      return
    }
    if (stream.status === "done" && stream.doneContent) {
      setMessages((prev) => {
        const msgs = [...prev]
        for (let i = msgs.length - 1; i >= 0; i--) {
          if (msgs[i].role === "assistant" && msgs[i].streaming) {
            msgs[i] = {
              ...msgs[i],
              content: stream.doneContent,
              streaming: false,
              messageId: stream.doneIds?.messageId,
              turnId: stream.doneIds?.turnId,
              runId: stream.doneIds?.runId,
            }
            break
          }
        }
        return msgs
      })
    }
  }, [stream.status, stream.doneContent, stream.doneIds])

  // 当前会话变化（选中历史 / 新建）时加载该 thread 的消息
  useEffect(() => {
    const tid = currentThreadId
    setVersionSelections({})
    setMessages([])
    void restoreHistory(tid).then((restored) => {
      const msgs: MatcherMessage[] = restored.map((r) => ({
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
    await startStream(currentThreadId, "/chat/match", { intent, thread_id: currentThreadId })
  }

  /** 重新生成保留旧版本；稳定 ID 走后端 regenerate，遗留无 ID 消息保留兼容重发。 */
  const handleRegenerate = async (turnId: string, messageId?: string) => {
    if (stream.status === "streaming") return
    const turn = groupTurns(messages).find((t) => t.id === turnId)
    if (!turn?.assistant || !turn.user.content) return
    setMessages((prev) => [...prev, { id: nextId(), role: "assistant", content: "", streaming: true }])
    jumpToLatest()
    if (messageId) await regenerateStream(currentThreadId, messageId)
    else await startStream(currentThreadId, "/chat/match", { intent: turn.user.content, thread_id: currentThreadId })
  }

  const handleEdit = (text: string) => {
    setInput(text)
    requestAnimationFrame(() => composerRef.current?.focus())
  }

  const handleNew = () => {
    setMessages([])
    useThreadStore.getState().registerThread("matcher")
  }

  const lastIsStreaming = stream.status === "streaming"

  return (
    <div className="flex h-full flex-col">
      <ConversationHeader
        parent="职位匹配"
        title={threadTitle ?? "新对话"}
        subtitle="输入求职方向，匹配官检索岗位"
        threadId={currentThreadId}
        onNew={handleNew}
        onSearch={search.openSearch}
        extra={
          <ConversationMenu
            threadId={currentThreadId}
            title={threadTitle ?? "新对话"}
            module="matcher"
            onAfterClear={() => void restoreHistory(currentThreadId)}
          />
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
                title="告诉匹配官你的方向"
                description={
                  <>
                    输入求职方向与背景后，
                    <br />
                    匹配官会搜索猎聘真实岗位并评估匹配度。
                  </>
                }
                accent={<AgentDots colors={["#0D9488", "#D97706", "#BE185D", "#7C3AED", "#2563EB"]} />}
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
                          label={meta.label}
                          color={meta.color}
                          streaming={asstStreaming}
                          completed={!asstStreaming}
                          thinking={stream.thinking}
                          initializing={asstStreaming && initializing}
                          initText="匹配官正在检索岗位"
                          workingText="正在检索岗位…"
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
            disabled={lastIsStreaming}
            streaming={lastIsStreaming}
            onStop={() => stopStream(currentThreadId)}
            placeholder="输入求职方向与背景，匹配官将自动检索岗位"
            hint="匹配官会搜索猎聘真实岗位并评估匹配度"
            toolbar
            textareaRef={composerRef}
            className="w-full"
          />
        </div>
        <ToastBubble message={toast} />
      </div>
    </div>
  )
}
