/** 简历上传与简历库的共享类型/工具（简历优化页 + 简历管理面板共用）。 */
import { apiFetch } from "@/lib/auth"

/** 简历上传任务（POST /api/resume/upload 返回 + GET /upload/{job_id} 轮询）。 */
export interface ResumeUploadJob {
  job_id: string
  filename: string
  status: "queued" | "running" | "done" | "error"
  stage: string
  progress: number
  error?: string | null
  result?: {
    resume_id: string
    filename: string
    doc_type: string
    char_count: number
    truncated: boolean
    content: string
  } | null
}

/** 简历库中的一条简历（GET /api/resume/library）。 */
export interface ResumeLibraryItem {
  resume_id: string
  filename: string
  doc_type: string
  char_count: number
  truncated: boolean
  created_at?: number
}

/** 可用于当前会话的简历（面板上传完成 / 点「用于当前对话」时回调）。 */
export interface ActiveResume {
  resume_id: string
  filename: string
  doc_type: string
  char_count: number
  content: string
}

/** 轮询上传任务直到 done / error（解析 PDF/图片可能较慢）。 */
export async function pollResumeUpload(
  jobId: string,
  { intervalMs = 1000, timeoutMs = 10 * 60 * 1000 } = {}
): Promise<ResumeUploadJob> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const resp = await apiFetch(`/api/resume/upload/${jobId}`)
    if (resp.ok) {
      const job: ResumeUploadJob = await resp.json()
      if (job.status === "done" || job.status === "error") return job
    }
    await new Promise((r) => setTimeout(r, intervalMs))
  }
  throw new Error("上传解析超时，请重试")
}

/** 读取简历库中某份简历的解析文本（点「用于当前对话」时）。 */
export async function fetchResumeContent(resumeId: string): Promise<string> {
  const resp = await apiFetch(`/api/resume/library/${encodeURIComponent(resumeId)}/content`)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  const data: { content: string } = await resp.json()
  return data.content
}
