import { useState } from "react"
import { Loader2, BookOpen, Check } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { MultilineInput } from "@/components/MultilineInput"
import { InitIndicator, ThinkingPulse } from "@/components/ThinkingIndicator"
import { MarkdownContent } from "@/components/MarkdownContent"
import { useChatStream } from "@/hooks/useChatStream"
import { cn } from "@/lib/utils"
import type { InterviewQA } from "@/types"

export default function InterviewPage() {
  const [topic, setTopic] = useState("")
  const stream = useChatStream()
  const [answer, setAnswer] = useState("")
  const [scoring, setScoring] = useState(false)
  const [qaList, setQaList] = useState<InterviewQA[]>([])

  const handleGenerate = async () => {
    setAnswer("")
    await stream.start("/interview/questions", { topic })
  }

  const handleScore = async () => {
    if (!stream.doneContent || !answer.trim()) return
    setScoring(true)
    try {
      const resp = await fetch("/api/interview/score", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: stream.doneContent, answer }),
      })
      const data = await resp.json()
      setQaList((prev) => [...prev, { question: stream.doneContent, answer, score: data.score, feedback: data.feedback }])
      setAnswer("")
    } finally {
      setScoring(false)
    }
  }

  const handleRecord = async () => {
    if (qaList.length === 0) return
    await fetch("/api/interview/record", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entries: qaList.map((qa) => ({ q: qa.question, a: qa.answer, score: qa.score })) }),
    })
    setQaList([])
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-16 shrink-0 items-center border-b px-6">
        <div>
          <h1 className="font-display text-xl font-semibold">面试练习</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">{"出题 → 答题 → 评分 → 记录"}</p>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto max-w-3xl space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm font-semibold">
                <BookOpen className="h-4 w-4" style={{ color: "#BE185D" }} />
                面试题生成
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <MultilineInput
                value={topic}
                onChange={setTopic}
                onSend={handleGenerate}
                disabled={stream.status === "streaming"}
                placeholder="输入主题（如：RAG、Agent、大模型应用），留空则随机出题"
              />
              <Button onClick={handleGenerate} disabled={stream.status === "streaming"} size="sm">
                {stream.status === "streaming" ? <><Loader2 className="mr-1 h-3 w-3 animate-spin" />生成中</> : "生成面试题"}
              </Button>

              {stream.status === "streaming" && (
                <div className="rounded-md border bg-muted/40 p-3">
                  {stream.initializing ? (
                    <InitIndicator text="正在生成面试题" />
                  ) : (
                    <>
                      <MarkdownContent className={cn(!stream.thinking && "typing-cursor")}>{stream.streamingText}</MarkdownContent>
                      {stream.thinking && <ThinkingPulse />}
                    </>
                  )}
                </div>
              )}
              {stream.status === "done" && stream.doneContent && (
                <div className="rounded-md border bg-muted/40 p-3">
                  <MarkdownContent>{stream.doneContent}</MarkdownContent>
                </div>
              )}
            </CardContent>
          </Card>

          {stream.doneContent && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold">你的回答</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <MultilineInput
                  value={answer}
                  onChange={setAnswer}
                  onSend={handleScore}
                  disabled={scoring}
                  placeholder="输入回答…（支持多行）"
                />
                <Button onClick={handleScore} disabled={scoring || !answer.trim()} size="sm">
                  {scoring ? <><Loader2 className="mr-1 h-3 w-3 animate-spin" />评分中</> : "提交评分"}
                </Button>
              </CardContent>
            </Card>
          )}

          {qaList.length > 0 && (
            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-3">
                <CardTitle className="text-sm font-semibold">评分记录</CardTitle>
                <Button onClick={handleRecord} size="sm" variant="outline">
                  <Check className="mr-1 h-3 w-3" />保存到记忆
                </Button>
              </CardHeader>
              <CardContent className="space-y-3">
                {qaList.map((qa, i) => <ScoreCard key={i} qa={qa} />)}
              </CardContent>
            </Card>
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

function ScoreCard({ qa }: { qa: InterviewQA }) {
  const score = qa.score ?? 0
  const color = score >= 8 ? "#0D9488" : score >= 5 ? "#D97706" : "#DC2626"
  return (
    <div className="rounded-md border bg-card p-3 space-y-2">
      <div>
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">问题</span>
        <p className="mt-0.5 text-sm leading-relaxed whitespace-pre-wrap">{qa.question.slice(0, 200)}…</p>
      </div>
      <div>
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">回答</span>
        <p className="mt-0.5 text-sm leading-relaxed whitespace-pre-wrap">{qa.answer.slice(0, 200)}…</p>
      </div>
      <div className="flex items-center gap-3 border-t pt-2">
        <span className="font-display text-lg font-bold" style={{ color }}>
          {score}<span className="text-sm text-muted-foreground">/10</span>
        </span>
        <span className="text-sm text-muted-foreground">{qa.feedback}</span>
      </div>
    </div>
  )
}
