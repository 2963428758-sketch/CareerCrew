import { useState } from "react"
import { Loader2, Users, Send } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { MultilineInput } from "@/components/MultilineInput"
import { InitIndicator, ThinkingPulse } from "@/components/ThinkingIndicator"
import { MarkdownContent } from "@/components/MarkdownContent"
import { useChatStream } from "@/hooks/useChatStream"
import { CONSULT_AGENTS } from "@/types"
import { cn } from "@/lib/utils"

export default function ConsultPage() {
  const [question, setQuestion] = useState("")
  const [selectedAgents, setSelectedAgents] = useState<string[]>(["salary_negotiator", "career_planner"])
  const stream = useChatStream()

  const toggleAgent = (id: string) => {
    setSelectedAgents((prev) => prev.includes(id) ? prev.filter((a) => a !== id) : [...prev, id])
  }

  const handleConsult = async () => {
    if (!question.trim() || selectedAgents.length === 0) return
    await stream.start("/consult", { question, agents: selectedAgents })
  }

  const agentLabels: Record<string, string> = Object.fromEntries(CONSULT_AGENTS.map((a) => [a.id, a.label]))
  const agentColors: Record<string, string> = Object.fromEntries(CONSULT_AGENTS.map((a) => [a.id, a.color]))

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-16 shrink-0 items-center border-b px-6">
        <div>
          <h1 className="font-display text-xl font-semibold">会诊</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">多位顾问并行分析，综合给出建议</p>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto max-w-3xl space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm font-semibold">
                <Users className="h-4 w-4 text-primary" />
                会诊问题
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <MultilineInput
                value={question}
                onChange={setQuestion}
                onSend={handleConsult}
                disabled={stream.status === "streaming"}
                placeholder="如：30K 字节跳动 offer 要不要接？"
              />
              <div className="flex flex-wrap gap-2">
                {CONSULT_AGENTS.map((agent) => {
                  const active = selectedAgents.includes(agent.id)
                  return (
                    <button
                      key={agent.id}
                      onClick={() => toggleAgent(agent.id)}
                      className={cn(
                        "flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-all",
                        active ? "text-white" : "border-border bg-card hover:bg-muted"
                      )}
                      style={active ? { backgroundColor: agent.color, borderColor: agent.color } : {}}
                    >
                      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: active ? "white" : agent.color }} />
                      {agent.label}
                    </button>
                  )
                })}
              </div>
              <Button onClick={handleConsult} disabled={stream.status === "streaming" || !question.trim() || selectedAgents.length === 0} size="sm">
                {stream.status === "streaming" ? <><Loader2 className="mr-1 h-3 w-3 animate-spin" />会诊中</> : <><Send className="mr-1 h-3 w-3" />开始会诊</>}
              </Button>
            </CardContent>
          </Card>

          {stream.status !== "idle" && (
            <div className="space-y-3">
              {stream.initializing && (
                <Card><CardContent className="p-4"><InitIndicator /></CardContent></Card>
              )}

              {stream.stage && !stream.initializing && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  {stream.stage === "consult" && <><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />各顾问正在并行分析</>}
                  {stream.stage === "synthesis" && <><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />正在综合意见</>}
                </div>
              )}

              {Object.entries(stream.agentChunks).map(([agentId, content]) => (
                <OpinionCard
                  key={agentId}
                  label={agentLabels[agentId] || agentId}
                  color={agentColors[agentId] || "#78716C"}
                  content={content}
                  isStreaming={stream.status === "streaming" && stream.stage === "consult"}
                  thinking={stream.thinking}
                />
              ))}

              {(stream.stage === "synthesis" || stream.doneContent) && (
                <Card className="stream-fade-in bg-primary/5">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-semibold text-primary">综合结论</CardTitle>
                  </CardHeader>
                  <CardContent>
                    {stream.status === "streaming" && stream.stage === "synthesis" && !stream.doneContent && !stream.streamingText ? (
                      <InitIndicator text="正在生成综合结论" />
                    ) : (
                      <>
                        <MarkdownContent className={cn(stream.status === "streaming" && stream.stage === "synthesis" && !stream.thinking && "typing-cursor")}>
                          {stream.doneContent || stream.streamingText}
                        </MarkdownContent>
                        {stream.status === "streaming" && stream.stage === "synthesis" && stream.streamingText && stream.thinking && <ThinkingPulse />}
                      </>
                    )}
                  </CardContent>
                </Card>
              )}
            </div>
          )}

          {stream.errorMsg && (
            <Card className="border-destructive">
              <CardContent className="p-4 text-sm text-destructive">{stream.errorMsg}</CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

function OpinionCard({ label, color, content, isStreaming, thinking }: {
  label: string
  color: string
  content: string
  isStreaming: boolean
  thinking: boolean
}) {
  return (
    <Card className="stream-fade-in">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
          <span className="text-xs font-semibold" style={{ color }}>{label}</span>
          {isStreaming && !content && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
        </div>
      </CardHeader>
      <CardContent>
        {content ? (
          <MarkdownContent className={cn(isStreaming && content && !thinking && "typing-cursor")}>{content}</MarkdownContent>
        ) : (
          <p className="text-sm text-muted-foreground">分析中…</p>
        )}
        {isStreaming && content && thinking && <ThinkingPulse />}
      </CardContent>
    </Card>
  )
}
