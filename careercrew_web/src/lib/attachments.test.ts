// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  deleteAttachment,
  listAttachments,
  MAX_ATTACHMENT_SIZE,
  pollSaveToKnowledge,
  saveAttachmentToKnowledge,
  uploadAttachment,
  validateAttachmentSelection,
  type Attachment,
} from "@/lib/attachments"

// ---- 依赖桩：apiFetch / apiErrorText ----
const apiFetch = vi.hoisted(() => vi.fn())
const apiErrorText = vi.hoisted(() => vi.fn(async () => "后端错误"))
vi.mock("@/lib/auth", () => ({ apiFetch }))
vi.mock("@/lib/errors", () => ({ apiErrorText }))

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
  } as Response
}

const ATTACHMENT: Attachment = {
  id: "att-1",
  thread_id: "t-1",
  original_filename: "报告.pdf",
  mime_type: "application/pdf",
  size_bytes: 1024,
  status: "uploaded",
  parser_type: null,
  parser_error: null,
  knowledge_document_id: null,
  created_at: "2025-01-01T00:00:00Z",
  expires_at: "2025-01-08T00:00:00Z",
}

describe("validateAttachmentSelection（客户端预检）", () => {
  it("接受白名单内的扩展名且在大小上限内", () => {
    expect(validateAttachmentSelection("a.pdf", 1024)).toBeNull()
    expect(validateAttachmentSelection("a.MD", 1024)).toBeNull() // 大小写不敏感
    expect(validateAttachmentSelection("a.xlsx", 1024)).toBeNull()
  })

  it("拒绝未知扩展名", () => {
    expect(validateAttachmentSelection("virus.exe", 1)).toContain("不支持的附件格式")
  })

  it("拒绝超 25MB", () => {
    expect(validateAttachmentSelection("a.pdf", MAX_ATTACHMENT_SIZE + 1)).toContain("25MB")
  })
})

describe("uploadAttachment", () => {
  beforeEach(() => {
    apiFetch.mockReset()
    apiErrorText.mockReset()
  })
  afterEach(() => vi.restoreAllMocks())

  it("以 multipart FormData 上传并携带 thread_id", async () => {
    apiFetch.mockResolvedValue(jsonResponse(ATTACHMENT))
    const file = new File(["x"], "报告.pdf", { type: "application/pdf" })
    const result = await uploadAttachment("t-1", file)

    expect(apiFetch).toHaveBeenCalledOnce()
    const [url, init] = apiFetch.mock.calls[0]
    expect(url).toBe("/api/chat/attachments")
    expect(init.method).toBe("POST")
    const form = init.body as FormData
    expect(form.get("thread_id")).toBe("t-1")
    expect(form.get("file")).toBe(file)
    expect(result.id).toBe("att-1")
  })

  it("失败时抛出中文错误", async () => {
    apiFetch.mockResolvedValue(jsonResponse({ detail: "x" }, false, 422))
    await expect(
      uploadAttachment("t-1", new File(["x"], "a.pdf"))
    ).rejects.toThrow("后端错误")
  })
})

describe("listAttachments / deleteAttachment / saveAttachmentToKnowledge", () => {
  beforeEach(() => {
    apiFetch.mockReset()
    apiErrorText.mockReset()
  })
  afterEach(() => vi.restoreAllMocks())

  it("listAttachments 带 thread_id 查询参数", async () => {
    apiFetch.mockResolvedValue(jsonResponse([ATTACHMENT]))
    const rows = await listAttachments("t-1")
    expect(apiFetch).toHaveBeenCalledWith("/api/chat/attachments?thread_id=t-1")
    expect(rows).toHaveLength(1)
  })

  it("deleteAttachment 发 DELETE 请求", async () => {
    apiFetch.mockResolvedValue(jsonResponse({ deleted: true }))
    await deleteAttachment("att-1")
    expect(apiFetch).toHaveBeenCalledWith(
      "/api/chat/attachments/att-1",
      { method: "DELETE" }
    )
  })

  it("saveAttachmentToKnowledge 发 POST 到 save-to-knowledge", async () => {
    apiFetch.mockResolvedValue(jsonResponse({ status: "parsing" }, true, 202))
    await saveAttachmentToKnowledge("att-1")
    expect(apiFetch).toHaveBeenCalledWith(
      "/api/chat/attachments/att-1/save-to-knowledge",
      { method: "POST" }
    )
  })
})

describe("pollSaveToKnowledge（轮询）", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    apiFetch.mockReset()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it("轮询直到 saved_to_knowledge 返回附件", async () => {
    // 前两次返回 parsing，第三次返回 saved_to_knowledge
    const parsing = { ...ATTACHMENT, status: "parsing" as const }
    const saved = {
      ...ATTACHMENT,
      status: "saved_to_knowledge" as const,
      knowledge_document_id: "doc-1",
      expires_at: null,
    }
    apiFetch
      .mockResolvedValueOnce(jsonResponse([parsing]))
      .mockResolvedValueOnce(jsonResponse([parsing]))
      .mockResolvedValueOnce(jsonResponse([saved]))

    const promise = pollSaveToKnowledge("t-1", "att-1", {
      intervalMs: 100,
      timeoutMs: 1000,
    })
    await vi.advanceTimersByTimeAsync(200)
    const result = await promise

    expect(result.status).toBe("saved_to_knowledge")
    expect(result.expires_at).toBeNull()
    expect(apiFetch.mock.calls.length).toBe(3)
  })

  it("ready（解析成功未入库）也视为终态避免死循环", async () => {
    const ready = { ...ATTACHMENT, status: "ready" as const }
    apiFetch.mockResolvedValue(jsonResponse([ready]))
    const result = await pollSaveToKnowledge("t-1", "att-1", {
      intervalMs: 100,
      timeoutMs: 1000,
    })
    expect(result.status).toBe("ready")
  })

  it("超时后抛出解析超时", async () => {
    apiFetch.mockResolvedValue(jsonResponse([{ ...ATTACHMENT, status: "parsing" }]))
    // 同步取得 promise 后立即挂上 .rejects，再推进计时器触发超时，避免 unhandled rejection
    const promise = pollSaveToKnowledge("t-1", "att-1", {
      intervalMs: 100,
      timeoutMs: 300,
    })
    const expectation = expect(promise).rejects.toThrow("解析超时")
    await vi.advanceTimersByTimeAsync(400)
    await expectation
  })
})
