import { useEffect, useRef, useState } from "react"
import { BookOpen, ChevronDown, CornerDownLeft, Send, Square } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { MultilineInput } from "@/components/MultilineInput"
import { InitIndicator, ThinkingPulse } from "@/components/ThinkingIndicator"
import { MarkdownContent } from "@/components/MarkdownContent"
import KnowledgePanel from "@/components/KnowledgePanel"
import { useChatStream } from "@/hooks/useChatStream"
import { AGENT_META, type KnowledgeSource } from "@/types"
import { cn } from "@/lib/utils"

interface KnowledgeMessage {
  id: string
  role: "user" | "assistant"
  content: string
  streaming?: boolean
  sources?: KnowledgeSource[]
}

let msgId = 0
const nextId = () => `kb-msg-${++msgId}`

/** 把 rag_query 返回的 [image: 绝对路径] 行转为 markdown 图片语法（仅本页）。 */
function renderKnowledgeText(text: string): string {
  return text.replace(
    /^\[image:\s*(.+?)\]\s*$/gm,
    (_m, path: string) => `![知识库图片](${String(path).replace(/\\/g, "/")})`
  )
}

export default function KnowledgePage() {
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<KnowledgeMessage[]>([])
  const [panelOpen, setPanelOpen] = useState(false)
  const [docCount, setDocCount] = useState<number | null>(null)
  const stream = useChatStream()
  const scrollRef = useRef<HTMLDivElement>(null)
  const meta = AGENT_META.knowledge_advisor

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [stream.streamingText, messages])

  // 右上角按钮展示库内文档数
  useEffect(() => {
    fetch("/api/knowledge")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setDocCount(d?.docs?.length ?? null))
      .catch(() => {})
  }, [panelOpen])

  useEffect(() => {
    if (stream.status === "done" && stream.doneContent) {
      setMessages((prev) => {
        const msgs = [...prev]
        for (let i = msgs.length - 1; i >= 0; i--) {
          if (msgs[i].role === "assistant" && msgs[i].streaming) {
            msgs[i] = { ...msgs[i], content: stream.doneContent, sources: stream.doneSources, streaming: false }
            break
          }
        }
        return msgs
      })
    }
  }, [stream.status, stream.doneContent, stream.doneSources])

  const handleAsk = async () => {
    const question = input
    if (!question.trim() || stream.status === "streaming") return
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", content: question },
      { id: nextId(), role: "assistant", content: "", streaming: true },
    ])
    setInput("")
    await stream.start("/knowledge/ask", { question })
  }

  const lastIsStreaming = stream.status === "streaming"

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-16 shrink-0 items-center justify-between border-b px-6">
        <div>
          <h1 className="font-display text-xl font-semibold">知识库问答</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">基于知识库文档检索回答，点击来源可查看原文</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => setPanelOpen((v) => !v)}>
          <BookOpen className="mr-1 h-3.5 w-3.5 text-primary" />
          知识库管理
          {docCount != null && <span className="ml-1 text-[11px] text-muted-foreground">（{docCount}）</span>}
        </Button>
      </header>

      <div className="relative flex-1 overflow-hidden">
        <div className="flex h-full flex-col">
          <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6">
            {messages.length === 0 && (
              <div className="mx-auto mt-16 max-w-md text-center">
                <div className="mb-6 flex justify-center">
                  <BookOpen className="h-10 w-10" style={{ color: meta.color }} />
                </div>
                <h2 className="font-display text-2xl font-semibold tracking-tight">向知识库提问</h2>
                <p className="mt-3 text-sm text-muted-foreground">
                  如"RAG 的检索流程是什么？"、"面试八股：HTTP 缓存策略"，
                  <br />
                  回答会标注数据来源，点击即可查看对应片段。
                </p>
              </div>
            )}
            <div className="mx-auto max-w-3xl space-y-4">
              {messages.map((msg) => (
                <MessageBubble
                  key={msg.id}
                  msg={msg}
                  isStreaming={lastIsStreaming && msg.role === "assistant" && (msg.streaming ?? false)}
                  streamingText={stream.streamingText}
                  thinking={stream.thinking}
                  initializing={stream.initializing}
                />
              ))}

              {stream.errorMsg && (
                <Card className="border-destructive">
                  <CardContent className="p-4 text-sm text-destructive">{stream.errorMsg}</CardContent>
                </Card>
              )}
            </div>
          </div>

          <div className="shrink-0 border-t bg-card/50 px-6 py-4">
            <div className="mx-auto flex max-w-3xl items-end gap-2">
              <MultilineInput
                value={input}
                onChange={setInput}
                onSend={handleAsk}
                disabled={stream.status === "streaming"}
                placeholder="输入问题，如：RAG 的检索流程是什么？"
              />
              {stream.status === "streaming" ? (
                <Button variant="destructive" size="icon" onClick={stream.stop} className="shrink-0">
                  <Square className="h-4 w-4" />
                </Button>
              ) : (
                <Button size="icon" onClick={handleAsk} disabled={!input.trim()} className="shrink-0">
                  <Send className="h-4 w-4" />
                </Button>
              )}
            </div>
            <p className="mx-auto mt-2 flex max-w-3xl items-center gap-1 text-[11px] text-muted-foreground">
              <CornerDownLeft className="h-3 w-3" /> 发送
              <span className="mx-1">·</span>
              Shift + Enter 换行 · 知识库图片会自动内嵌显示
            </p>
          </div>
        </div>

        {/* 右上角知识库管理抽屉 */}
        {panelOpen && (
          <aside className="absolute inset-y-0 right-0 z-20 w-[400px] overflow-y-auto border-l bg-background/95 p-4 shadow-2xl backdrop-blur">
            <KnowledgePanel onClose={() => setPanelOpen(false)} />
          </aside>
        )}
      </div>
    </div>
  )
}

function MessageBubble({ msg, isStreaming, streamingText, thinking, initializing }: {
  msg: KnowledgeMessage
  isStreaming: boolean
  streamingText: string
  thinking: boolean
  initializing: boolean
}) {
  const isUser = msg.role === "user"
  const meta = AGENT_META.knowledge_advisor
  const content = isStreaming ? streamingText : msg.content

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-lg rounded-br-sm bg-primary px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap text-primary-foreground">
          {content}
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start">
      <div className="stream-fade-in max-w-[85%] rounded-lg rounded-bl-sm border bg-card px-4 py-3">
        <div className="mb-1.5 flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: meta.color }} />
          <span className="text-xs font-semibold" style={{ color: meta.color }}>{meta.label}</span>
        </div>
        {isStreaming && !content && initializing ? (
          <InitIndicator text="正在检索知识库" />
        ) : (
          <>
            <MarkdownContent className={cn(isStreaming && content && !thinking && "typing-cursor")}>
              {renderKnowledgeText(content || "")}
            </MarkdownContent>
            {isStreaming && content && thinking && <ThinkingPulse />}
            {!isStreaming && msg.sources && msg.sources.length > 0 && <SourceList sources={msg.sources} />}
          </>
        )}
      </div>
    </div>
  )
}

function SourceList({ sources }: { sources: KnowledgeSource[] }) {
  const [open, setOpen] = useState<Set<number>>(new Set())

  const toggle = (i: number) => {
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  }

  return (
    <div className="mt-3 space-y-1.5 border-t pt-2">
      <p className="text-[11px] font-medium text-muted-foreground">
        数据来源（{sources.length}）· 点击查看原文
      </p>
      {sources.map((s, i) => {
        const expanded = open.has(i)
        const name = s.doc || s.source.split(/[\\/]/).pop() || `来源 ${i + 1}`
        return (
          <div key={`${s.doc}-${i}`} className="overflow-hidden rounded-md border bg-muted/30">
            <button
              onClick={() => toggle(i)}
              className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left transition-colors hover:bg-muted"
            >
              <span className="text-[10px] font-semibold text-primary">[{i + 1}]</span>
              <span className="min-w-0 flex-1 truncate text-xs font-medium">{name}</span>
              <span className="shrink-0 text-[10px] text-muted-foreground">相关度 {s.score.toFixed(2)}</span>
              <ChevronDown className={cn("h-3 w-3 shrink-0 text-muted-foreground transition-transform", expanded && "rotate-180")} />
            </button>
            {expanded && (
              <div className="border-t bg-card px-3 py-2">
                {s.image_path && (
                  <p className="mb-1.5 truncate text-[10px] text-muted-foreground">
                    图片：{s.image_path.replace(/\\/g, "/")}
                  </p>
                )}
                <p className="whitespace-pre-wrap text-xs leading-relaxed text-foreground/90">{s.text}</p>
                <p className="mt-1.5 truncate text-[10px] text-muted-foreground">来源：{s.source || s.doc}</p>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
