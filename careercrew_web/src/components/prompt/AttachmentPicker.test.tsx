// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { AttachmentPicker } from "@/components/prompt/AttachmentPicker"
import type { Attachment } from "@/lib/attachments"

// ---- 依赖桩：lib 层 mock，隔离组件行为 ----
const listAttachments = vi.hoisted(() => vi.fn())
const uploadAttachment = vi.hoisted(() => vi.fn())
const deleteAttachment = vi.hoisted(() => vi.fn())
const saveAttachmentToKnowledge = vi.hoisted(() => vi.fn())
const pollSaveToKnowledge = vi.hoisted(() => vi.fn())
const validateAttachmentSelection = vi.hoisted(() => vi.fn(() => null as string | null))

vi.mock("@/lib/attachments", () => ({
  listAttachments,
  uploadAttachment,
  deleteAttachment,
  saveAttachmentToKnowledge,
  pollSaveToKnowledge,
  validateAttachmentSelection,
  ATTACHMENT_EXTENSIONS: [
    ".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt", ".png", ".jpg", ".jpeg",
  ],
  MAX_ATTACHMENT_SIZE: 25 * 1024 * 1024,
}))

function att(overrides: Partial<Attachment> = {}): Attachment {
  return {
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
    ...overrides,
  }
}

describe("AttachmentPicker", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listAttachments.mockResolvedValue([])
    uploadAttachment.mockReset()
    deleteAttachment.mockReset()
    saveAttachmentToKnowledge.mockReset()
  })
  afterEach(() => vi.restoreAllMocks())

  it("渲染已有附件 chips（名称/大小/状态）", async () => {
    listAttachments.mockResolvedValue([att()])
    render(<AttachmentPicker threadId="t-1" />)
    const chip = await screen.findByTestId("attachment-chip")
    expect(chip.textContent).toContain("报告.pdf")
    expect(chip.textContent).toContain("1.0 KB")
    expect(chip.textContent).toContain("已上传")
  })

  it("选择文件：客户端预检失败时显示错误且不发起上传", async () => {
    validateAttachmentSelection.mockReturnValue("不支持的附件格式：virus.exe")
    uploadAttachment.mockResolvedValue(att())
    render(<AttachmentPicker threadId="t-1" />)

    const input = screen.getByTestId("attachment-file-input")
    const file = new File(["x"], "virus.exe")
    fireEvent.change(input, { target: { files: [file] } })

    await screen.findByText(/不支持的附件格式/)
    expect(uploadAttachment).not.toHaveBeenCalled()
  })

  it("选择文件：预检通过则上传并在 chips 中展示", async () => {
    uploadAttachment.mockResolvedValue(att())
    render(<AttachmentPicker threadId="t-1" />)

    const input = screen.getByTestId("attachment-file-input")
    const file = new File(["x"], "报告.pdf", { type: "application/pdf" })
    fireEvent.change(input, { target: { files: [file] } })

    await screen.findByTestId("attachment-chip")
    expect(uploadAttachment).toHaveBeenCalledWith("t-1", file)
    expect(screen.getByTestId("attachment-chip").textContent).toContain("报告.pdf")
  })

  it("上传失败可重试：失败抛错显示错误信息", async () => {
    listAttachments.mockResolvedValue([])
    uploadAttachment.mockRejectedValue(new Error("附件超过 25MB 限制"))
    render(<AttachmentPicker threadId="t-1" />)
    const input = screen.getByTestId("attachment-file-input")
    fireEvent.change(input, {
      target: { files: [new File(["x"], "big.pdf", { type: "application/pdf" })] },
    })
    await screen.findByText(/25MB/)
  })

  it("删除（二次确认）后从列表移除", async () => {
    listAttachments.mockResolvedValue([att()])
    deleteAttachment.mockResolvedValue(undefined)
    render(<AttachmentPicker threadId="t-1" />)

    await screen.findByTestId("attachment-chip")
    fireEvent.click(screen.getByRole("button", { name: "删除 报告.pdf" }))
    // 二次确认对话框
    await screen.findByText("确认删除「报告.pdf」？")
    fireEvent.click(screen.getByRole("button", { name: "删除" }))

    await waitFor(() => {
      expect(deleteAttachment).toHaveBeenCalledWith("att-1")
      expect(screen.queryByTestId("attachment-chip")).toBeNull()
    })
  })

  it("「存入知识库」ready 后可用并触发 save + 轮询刷新状态", async () => {
    listAttachments.mockResolvedValue([att({ status: "ready" })]) // 初始
    saveAttachmentToKnowledge.mockResolvedValue(undefined)
    pollSaveToKnowledge.mockResolvedValue(
      att({ status: "saved_to_knowledge", knowledge_document_id: "doc-1", expires_at: null })
    )
    render(<AttachmentPicker threadId="t-1" />)

    await screen.findByTestId("attachment-chip")
    // ready 态 chip 上应出现「存入知识库」按钮
    const saveBtn = screen.getByRole("button", { name: "将 报告.pdf 存入知识库" })
    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(saveAttachmentToKnowledge).toHaveBeenCalledWith("att-1")
      expect(pollSaveToKnowledge).toHaveBeenCalledWith("t-1", "att-1")
      expect(screen.getByTestId("attachment-chip").textContent).toContain("已入知识库")
    })
  })

  it("附件状态变更触发 onAttachmentsChange 回调", async () => {
    listAttachments.mockResolvedValue([att()])
    const onChange = vi.fn()
    render(<AttachmentPicker threadId="t-1" onAttachmentsChange={onChange} />)
    await screen.findByTestId("attachment-chip")
    expect(onChange).toHaveBeenCalledWith(expect.arrayContaining([
      expect.objectContaining({ id: "att-1" }),
    ]))
  })
})
