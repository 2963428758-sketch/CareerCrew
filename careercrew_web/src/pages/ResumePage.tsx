import { useRef, useState, type DragEvent } from "react"
import { Upload, FileText, Image as ImageIcon, File, Loader2, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Textarea } from "@/components/ui/textarea"
import { InitIndicator, ThinkingPulse } from "@/components/ThinkingIndicator"
import { MarkdownContent } from "@/components/MarkdownContent"
import { useChatStream } from "@/hooks/useChatStream"
import { cn } from "@/lib/utils"

interface UploadResult {
  filename: string
  doc_type: string
  content: string
  truncated: boolean
  char_count: number
}

export default function ResumePage() {
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null)
  const [resumeText, setResumeText] = useState("")
  const [jdText, setJdText] = useState("")
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const stream = useChatStream()

  const handleUpload = async (file: File) => {
    setUploading(true)
    try {
      const form = new FormData()
      form.append("file", file)
      const resp = await fetch("/api/resume/upload", { method: "POST", body: form })
      const data: UploadResult = await resp.json()
      setUploadResult(data)
      setResumeText(data.content)
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

  const handleGenerate = async () => {
    if (!resumeText.trim()) return
    await stream.start("/resume/generate", { user_resume: resumeText, jd: jdText })
  }

  const docTypeIcon = uploadResult?.doc_type === "image" ? ImageIcon : uploadResult?.doc_type === "text" ? FileText : File

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-16 shrink-0 items-center border-b px-6">
        <div>
          <h1 className="font-display text-xl font-semibold">简历优化</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">上传简历，按目标 JD 定制优化</p>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto max-w-3xl space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold">上传简历</CardTitle>
            </CardHeader>
            <CardContent>
              <div
                className={cn(
                  "flex min-h-[120px] cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 transition-colors",
                  dragOver ? "border-primary bg-primary/5" : "border-border hover:border-muted-foreground/40"
                )}
                onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => !uploading && fileInputRef.current?.click()}
              >
                {uploading ? (
                  <div className="flex flex-col items-center gap-2">
                    <Loader2 className="h-7 w-7 animate-spin text-primary" />
                    <p className="text-sm text-muted-foreground">正在解析简历…</p>
                  </div>
                ) : uploadResult ? (
                  <div className="flex items-center gap-3">
                    {(() => {
                      const Icon = docTypeIcon
                      return <Icon className="h-7 w-7" style={{ color: "#D97706" }} />
                    })()}
                    <div>
                      <p className="text-sm font-medium">{uploadResult.filename}</p>
                      <p className="text-xs text-muted-foreground">{uploadResult.doc_type} · {uploadResult.char_count} 字符</p>
                    </div>
                  </div>
                ) : (
                  <>
                    <Upload className="mb-2 h-6 w-6 text-muted-foreground/60" />
                    <p className="text-sm text-muted-foreground">
                      拖拽文件到此处，或
                      <span className="ml-1 font-medium text-primary">
                        点击选择
                      </span>
                    </p>
                    <p className="mt-1 text-[11px] text-muted-foreground/70">PNG / JPG / TXT / MD / PDF / DOCX · 最大 20MB</p>
                  </>
                )}
                <input
                  ref={fileInputRef}
                  type="file"
                  className="hidden"
                  accept=".png,.jpg,.jpeg,.gif,.bmp,.webp,.txt,.md,.markdown,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx"
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) handleUpload(f) }}
                />
              </div>

              {uploadResult?.truncated && (
                <p className="mt-2 text-xs text-accent">内容超过 200k 字符已截断，可能影响优化质量</p>
              )}
              {uploadResult && (
                <div className="mt-2 flex gap-2">
                  <Badge variant="outline">{uploadResult.doc_type}</Badge>
                  <Badge variant="secondary">{uploadResult.char_count} chars</Badge>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold">简历内容 <span className="text-xs font-normal text-muted-foreground">可编辑</span></CardTitle>
            </CardHeader>
            <CardContent>
              <Textarea
                value={resumeText}
                onChange={(e) => setResumeText(e.target.value)}
                className="min-h-[180px] font-mono text-[13px] leading-relaxed"
                placeholder="上传后自动填充，或直接粘贴简历文本…"
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold">目标 JD <span className="text-xs font-normal text-muted-foreground">可选</span></CardTitle>
            </CardHeader>
            <CardContent>
              <Textarea
                value={jdText}
                onChange={(e) => setJdText(e.target.value)}
                className="min-h-[90px] text-[13px] leading-relaxed"
                placeholder="粘贴目标岗位的 JD…"
              />
            </CardContent>
          </Card>

          <Button onClick={handleGenerate} disabled={stream.status === "streaming" || !resumeText.trim()} className="w-full" size="lg">
            {stream.status === "streaming" ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />优化中</> : <><Sparkles className="mr-2 h-4 w-4" />AI 优化简历</>}
          </Button>

          {stream.status === "streaming" && (
            <Card className="stream-fade-in">
              <CardContent className="p-4">
                {stream.initializing ? (
                  <InitIndicator text="正在优化简历" />
                ) : (
                  <>
                    <MarkdownContent className={cn(!stream.thinking && "typing-cursor")}>{stream.streamingText}</MarkdownContent>
                    {stream.thinking && <ThinkingPulse />}
                  </>
                )}
              </CardContent>
            </Card>
          )}
          {stream.status === "done" && stream.doneContent && (
            <Card className="stream-fade-in">
              <CardHeader className="pb-2"><CardTitle className="text-sm font-semibold">优化结果</CardTitle></CardHeader>
              <CardContent><MarkdownContent>{stream.doneContent}</MarkdownContent></CardContent>
            </Card>
          )}

          {stream.errorMsg && (
            <Card className="border-destructive"><CardContent className="p-4 text-sm text-destructive">{stream.errorMsg}</CardContent></Card>
          )}
        </div>
      </div>
    </div>
  )
}
