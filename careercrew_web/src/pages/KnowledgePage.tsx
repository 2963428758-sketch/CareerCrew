import { useEffect, useMemo, useRef, useState } from "react"
import { BookOpen } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { PromptComposer } from "@/components/prompt/PromptComposer"
import { AttachmentPicker, type AttachmentPickerHandle } from "@/components/prompt/AttachmentPicker"
import { toMessageAttachments, type Attachment } from "@/lib/attachments"
import { EmptyState, AgentDots } from "@/components/workspace/EmptyState"
import KnowledgePanel from "@/components/KnowledgePanel"
import { JumpToLatest } from "@/components/JumpToLatest"
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
import { useThreadStore, type ThreadItem } from "@/store/threadStore"
import { IDLE_SESSION, useStreamStore } from "@/store/streamStore"
import type { KnowledgeSource } from "@/types"
import { restoreHistory } from "@/lib/historyRestore"
import { ImageLightbox } from "@/components/knowledge/ImageLightbox"
import { KnowledgeAssistant } from "@/components/knowledge/KnowledgeAssistant"
import { KnowledgeScopeBar, type KnowledgeScope } from "@/components/knowledge/KnowledgeScopeBar"
import { nextId, type KnowledgeMessage } from "@/components/knowledge/types"

/** zustand v5 + React 19：selector 返回新数组会触发 useSyncExternalStore 无限循环，用模块级常量兜底。 */
const EMPTY_THREADS: ThreadItem[] = []

export default function KnowledgePage() {
  const [input, setInput] = useState("")
  const attachRef = useRef<AttachmentPickerHandle>(null)
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [messages, setMessages] = useState<KnowledgeMessage[]>([])
  const [panelOpen, setPanelOpen] = useState(false)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const currentThreadId = useThreadStore((s) => s.currentThreadByModule.knowledge)
  // 会话标题：首条消息后由 touchThread 落库，展示在 Header 左侧
  const threadTitle = useThreadStore((s) =>
    s.threadsByModule.knowledge?.find((t) => t.thread_id === s.currentThreadByModule.knowledge)?.title
  )
  // 检索范围：存于会话元数据（retrieval_scope），切换会话自动恢复，修改即时 PATCH 持久化
  const threads = useThreadStore((s) => s.threadsByModule.knowledge ?? EMPTY_THREADS)
  const setThreadScope = useThreadStore((s) => s.setThreadScope)
  const savedScope = threads.find((t) => t.thread_id === currentThreadId)?.retrieval_scope
  // 范围与分类是两个正交维度：可同时选中（如「公共库 · 面试题」）
  const scope: KnowledgeScope = savedScope?.type ?? "all"
  const category = savedScope?.category_id ?? ""
  const changeCategory = (id: string) => {
    void setThreadScope("knowledge", currentThreadId, { type: scope, category_id: id || null })
  }
  const changeScope = (next: KnowledgeScope) => {
    void setThreadScope("knowledge", currentThreadId, { type: next, category_id: category || null })
  }
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
              sources: stream.doneSources,
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
  }, [stream.status, stream.doneContent, stream.doneSources, stream.doneIds])

  // 当前会话变化（选中历史 / 新建）时加载该 thread 的消息
  useEffect(() => {
    const tid = currentThreadId
    setVersionSelections({})
    setMessages([])
    setPreviewUrl(null)
    void restoreHistory(tid).then((restored) => {
      // latest-wins：快速连续切换会话时丢弃迟到的旧响应，防止覆盖新会话消息
      if (useThreadStore.getState().currentThreadByModule.knowledge !== tid) return
      const msgs: KnowledgeMessage[] = restored.map((r) => {
        const sources = Array.isArray(r.metadata?.sources)
          ? (r.metadata.sources as KnowledgeSource[])
          : Array.isArray(r.raw?.sources)
            ? (r.raw.sources as KnowledgeSource[])
            : undefined
        const msg: KnowledgeMessage = {
          id: nextId(),
          role: r.role,
          content: r.content,
          messageId: r.messageId,
          turnId: r.turnId,
          runId: r.runId,
          attachments: r.attachments,
        }
        if (sources && r.role === "assistant") msg.sources = sources
        return msg
      })
      // 切回一个仍在流式回答的会话：补一个流式占位气泡（状态从 store 实时读）
      const live = useStreamStore.getState().sessions[tid]
      setMessages(live && live.status === "streaming"
        ? [...msgs, { id: nextId(), role: "assistant", content: "", streaming: true }]
        : msgs)
      jumpToLatest()
    })
  }, [currentThreadId, jumpToLatest])

  const handleAsk = async () => {
    const question = input
    if (!question.trim() || stream.status === "streaming") return
    const isFirst = messages.length === 0
    const turnAttachments = attachments
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", content: question, attachments: toMessageAttachments(turnAttachments) },
      { id: nextId(), role: "assistant", content: "", streaming: true },
    ])
    setInput("")
    jumpToLatest()
    if (isFirst) useThreadStore.getState().touchThread("knowledge", currentThreadId, question)
    const body: Record<string, unknown> = {
      question, thread_id: currentThreadId, category, scope,
    }
    if (turnAttachments.length) body.attachments = turnAttachments.map((a) => ({ id: a.id }))
    attachRef.current?.clear()
    await startStream(currentThreadId, "/knowledge/ask", body)
  }

  /** 重新生成保留旧版本；稳定 ID 走后端 regenerate，遗留无 ID 消息保留兼容重发。 */
  const handleRegenerate = async (turnId: string, messageId?: string) => {
    if (stream.status === "streaming") return
    const turn = groupTurns(messages).find((t) => t.id === turnId)
    if (!turn?.assistant || !turn.user.content) return
    const targetTurnId = turn.assistant.turnId || turn.user.turnId || turn.id
    const nextVerIndex = (turn.versions?.length ?? 1)
    setVersionSelections((prev) => ({ ...prev, [turn.id]: nextVerIndex }))
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "assistant", content: "", streaming: true, turnId: targetTurnId },
    ])
    jumpToLatest()
    if (messageId) await regenerateStream(currentThreadId, messageId)
    else await startStream(currentThreadId, "/knowledge/ask", {
      question: turn.user.content, thread_id: currentThreadId, category, scope,
    })
  }

  const handleEdit = (text: string) => {
    setInput(text)
    requestAnimationFrame(() => composerRef.current?.focus())
  }

  const handleNew = () => {
    setMessages([])
    setPreviewUrl(null)
    useThreadStore.getState().registerThread("knowledge")
  }

  const lastIsStreaming = stream.status === "streaming"

  return (
    <div className="flex h-full flex-col">
      <ConversationHeader
        parent="知识库问答"
        title={threadTitle ?? "新对话"}
        subtitle="基于知识库文档检索回答，点击来源可查看原文"
        threadId={currentThreadId}
        onNew={handleNew}
        onSearch={search.openSearch}
        extra={
          <>
            <HeaderIconAction label="知识库面板" onClick={() => setPanelOpen((v) => !v)}>
              <BookOpen className="h-4 w-4" strokeWidth={1.7} />
            </HeaderIconAction>
            <ConversationMenu
              threadId={currentThreadId}
              title={threadTitle ?? "新对话"}
              module="knowledge"
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
                title="向知识库提问"
                description={
                  <>
                    输入问题后，自动检索知识库并生成回答；
                    <br />
                    回答会标注数据来源，点击即可查看对应片段。
                  </>
                }
                accent={<AgentDots colors={["#16A34A", "#D97706", "#BE185D", "#7C3AED", "#2563EB"]} />}
              />
            ) : (
              <div className="flex flex-col gap-10">
                {turns.map((turn, i) => {
                  const isLast = i === turns.length - 1
                  const versions = turn.versions ?? (turn.assistant ? [turn.assistant] : [])
                  const selectedVersion = Math.min(versionSelections[turn.id] ?? versions.length - 1, versions.length - 1)
                  const asst = versions[selectedVersion]
                  const isNewestVersion = selectedVersion === versions.length - 1
                  const asstStreaming = Boolean(asst?.streaming) && lastIsStreaming && isNewestVersion
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
                        <KnowledgeAssistant
                          msg={asst}
                          threadId={currentThreadId}
                          isStreaming={asstStreaming}
                          streamingText={stream.streamingText}
                          thinking={stream.thinking}
                          initializing={initializing}
                          onPreview={setPreviewUrl}
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
            onSend={handleAsk}
            disabled={lastIsStreaming}
            streaming={lastIsStreaming}
            onStop={() => stopStream(currentThreadId)}
            placeholder="输入问题，将自动检索知识库后回答"
            hint="知识库图片会自动内嵌显示"
            toolbar
            onAddAttachment={() => attachRef.current?.pick()}
            attachments={<AttachmentPicker ref={attachRef} embedded threadId={currentThreadId} disabled={lastIsStreaming} onAttachmentsChange={setAttachments} />}
            textareaRef={composerRef}
            className="w-full"
            header={
              <KnowledgeScopeBar
                scope={scope}
                category={category}
                onScope={changeScope}
                onCategory={changeCategory}
              />
            }
          />
        </div>
        <ToastBubble message={toast} />

        {/* 右上角知识库管理抽屉 */}
        {panelOpen && (
          <aside className="absolute inset-y-0 right-0 z-20 w-[400px] overflow-y-auto border-l border-[var(--border-soft)] bg-workspace p-4">
            <KnowledgePanel onClose={() => setPanelOpen(false)} />
          </aside>
        )}

        {previewUrl && <ImageLightbox src={previewUrl} onClose={() => setPreviewUrl(null)} />}
      </div>
    </div>
  )
}
