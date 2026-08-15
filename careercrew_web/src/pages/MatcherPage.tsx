import { useEffect, useMemo, useRef, useState } from "react"
import { Plus, Target } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
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
import { AGENT_META } from "@/types"
import { apiFetch } from "@/lib/auth"

interface MatcherMessage {
  id: string
  role: "user" | "assistant"
  content: string
  streaming?: boolean
}

let msgId = 0
const nextId = () => `match-msg-${++msgId}`

export default function MatcherPage() {
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<MatcherMessage[]>([])
  const currentThreadId = useThreadStore((s) => s.currentThreadByModule.matcher)
  // 每会话独立流：切换会话不影响其他会话正在进行的回答
  const stream = useStreamStore((s) => s.sessions[currentThreadId] ?? IDLE_SESSION)
  const startStream = useStreamStore((s) => s.start)
  const stopStream = useStreamStore((s) => s.stop)
  const { scrollRef, showJumpToLatest, jumpToLatest } = useChatScroll([stream.streamingText, messages])
  const initializing = stream.status === "streaming" && stream.streamingText === "" && Object.keys(stream.agentChunks).length === 0
  const meta = AGENT_META.job_matcher

  // ── Turn 分组 + Anchor Rail 导航 ──
  const turns = useMemo(() => groupTurns(messages), [messages])
  const turnIds = useMemo(() => turns.map((t) => t.user.id), [turns])
  const { activeId, selectTurn, highlightId } = useConversationNavigation(turnIds, scrollRef)
  const { toast, showToast } = useToast()
  const composerRef = useRef<HTMLTextAreaElement | null>(null)

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
            msgs[i] = { ...msgs[i], content: stream.doneContent, streaming: false }
            break
          }
        }
        return msgs
      })
    }
  }, [stream.status, stream.doneContent])

  // 当前会话变化（选中历史 / 新建）时加载该 thread 的消息
  useEffect(() => {
    const tid = currentThreadId
    setMessages([])
    apiFetch(`/api/memory?thread_id=${tid}`)
      .then((r) => r.json())
      .then((entries: Record<string, unknown>[]) => {
        const msgs: MatcherMessage[] = []
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

  /** 重新生成：移除该回答后重发同一问题（不新建用户消息） */
  const handleRegenerate = async (turnId: string) => {
    if (stream.status === "streaming") return
    const turn = groupTurns(messages).find((t) => t.id === turnId)
    if (!turn?.assistant || !turn.user.content) return
    const removedId = turn.assistant.id
    setMessages((prev) => prev.filter((m) => m.id !== removedId))
    setMessages((prev) => [...prev, { id: nextId(), role: "assistant", content: "", streaming: true }])
    jumpToLatest()
    await startStream(currentThreadId, "/chat/match", { intent: turn.user.content, thread_id: currentThreadId })
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
      <WorkspaceHeader
        title="职位匹配"
        subtitle="输入求职方向，匹配官检索岗位"
        actions={
          <Button variant="outline" size="sm" onClick={handleNew}>
            <Plus className="mr-1 h-3.5 w-3.5" strokeWidth={1.7} />新对话
          </Button>
        }
      />

      <div className="relative flex-1 overflow-hidden">
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
                accent={<Target className="h-5 w-5" style={{ color: meta.color }} strokeWidth={1.7} />}
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
                      isUser={turn.user.role === "user"}
                      highlighted={highlightId === turn.id}
                      onEdit={handleEdit}
                    >
                      {asst && (
                        <AssistantMessage
                          messageId={asst.id}
                          content={content}
                          label={meta.label}
                          color={meta.color}
                          streaming={asstStreaming}
                          thinking={stream.thinking}
                          initializing={asstStreaming && initializing}
                          initText="匹配官正在检索岗位"
                          workingText="正在检索岗位…"
                          onRegenerate={
                            isLast && !asstStreaming && Boolean(asst.content) && Boolean(turn.user.content)
                              ? () => handleRegenerate(turn.id)
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
            textareaRef={composerRef}
            className="w-full"
          />
        </div>
        <ToastBubble message={toast} />
      </div>
    </div>
  )
}
