// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { FeedbackArea } from "@/components/conversation/FeedbackArea"
import { resetFeedbackStateForTest } from "@/lib/feedbackState"

const putMessageFeedback = vi.hoisted(() => vi.fn())
const deleteMessageFeedback = vi.hoisted(() => vi.fn())
const getThreadFeedback = vi.hoisted(() => vi.fn())
const notifyError = vi.hoisted(() => vi.fn())
vi.mock("@/lib/feedback", () => ({ putMessageFeedback, deleteMessageFeedback, getThreadFeedback }))
vi.mock("@/lib/toastBus", () => ({ notifyError }))

const saved = (messageId: string, rating: "positive" | "negative" = "positive") => ({
  id: `feedback-${messageId}`, messageId, rating, shareContext: false,
})

describe("FeedbackArea persisted interactions", () => {
  beforeEach(() => {
    resetFeedbackStateForTest()
    putMessageFeedback.mockReset()
    deleteMessageFeedback.mockReset()
    getThreadFeedback.mockReset().mockResolvedValue([])
    notifyError.mockReset()
  })
  afterEach(() => resetFeedbackStateForTest())

  it("点赞不乐观更新，成功后才选中；第二次点击撤销", async () => {
    let resolvePut!: (value: ReturnType<typeof saved>) => void
    putMessageFeedback.mockReturnValue(new Promise((resolve) => { resolvePut = resolve }))
    deleteMessageFeedback.mockResolvedValue(undefined)
    render(<FeedbackArea threadId="thread-1" messageId="answer-v1" content="回答" />)
    await waitFor(() => expect(getThreadFeedback).toHaveBeenCalledWith("thread-1"))
    fireEvent.click(screen.getByRole("button", { name: "有帮助" }))
    expect((screen.getByRole("button", { name: "有帮助" }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByRole("button", { name: "有帮助" }).getAttribute("aria-pressed")).not.toBe("true")
    resolvePut(saved("answer-v1"))
    await waitFor(() => expect(screen.getByRole("button", { name: "取消反馈" }).getAttribute("aria-pressed")).toBe("true"))
    fireEvent.click(screen.getByRole("button", { name: "取消反馈" }))
    await waitFor(() => expect(deleteMessageFeedback).toHaveBeenCalledWith("answer-v1"))
    await waitFor(() => expect(screen.getByRole("button", { name: "有帮助" }).getAttribute("aria-pressed")).not.toBe("true"))
  })

  it("点踩提交带原因、说明和默认关闭的明确授权", async () => {
    putMessageFeedback.mockResolvedValue({ ...saved("answer-v1", "negative"), reason: "citation_failure", comment: "来源不对", shareContext: true })
    render(<FeedbackArea threadId="thread-1" messageId="answer-v1" content="回答" />)
    await waitFor(() => expect(getThreadFeedback).toHaveBeenCalled())
    fireEvent.click(screen.getByRole("button", { name: "不满意" }))
    expect((screen.getByLabelText("允许保存脱敏后的相关对话片段，用于产品质量改进") as HTMLInputElement).checked).toBe(false)
    fireEvent.click(screen.getByText("引用 / 来源有问题"))
    fireEvent.change(screen.getByPlaceholderText("补充说明（可选）"), { target: { value: "来源不对" } })
    fireEvent.click(screen.getByLabelText("允许保存脱敏后的相关对话片段，用于产品质量改进"))
    fireEvent.click(screen.getByRole("button", { name: "提交" }))
    await waitFor(() => expect(putMessageFeedback).toHaveBeenCalledWith("answer-v1", {
      rating: "negative", reason: "citation_failure", comment: "来源不对", shareContext: true,
    }))
  })

  it("恢复按稳定 message ID 绑定，重生成版本彼此独立", async () => {
    getThreadFeedback.mockResolvedValue([saved("answer-v1")])
    render(<><FeedbackArea threadId="thread-1" messageId="answer-v1" content="旧版本" /><FeedbackArea threadId="thread-1" messageId="answer-v2" content="新版本" /></>)
    await waitFor(() => expect(screen.getByRole("button", { name: "取消反馈" })).toBeTruthy())
    expect(screen.getAllByRole("button", { name: "不满意" })).toHaveLength(2)
  })

  it("失败保留未选状态并走全局错误提示", async () => {
    putMessageFeedback.mockRejectedValue(new Error("保存失败"))
    render(<FeedbackArea threadId="thread-1" messageId="answer-v1" content="回答" />)
    await waitFor(() => expect(getThreadFeedback).toHaveBeenCalled())
    fireEvent.click(screen.getByRole("button", { name: "有帮助" }))
    await waitFor(() => expect(notifyError).toHaveBeenCalledWith("保存失败"))
    expect(screen.getByRole("button", { name: "有帮助" }).getAttribute("aria-pressed")).not.toBe("true")
  })
})
