// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest"
import { deleteMessageFeedback, getThreadFeedback, putMessageFeedback } from "@/lib/feedback"

const apiFetch = vi.hoisted(() => vi.fn())
const apiErrorText = vi.hoisted(() => vi.fn(async () => "后端错误"))
vi.mock("@/lib/auth", () => ({ apiFetch }))
vi.mock("@/lib/errors", () => ({
  apiErrorText,
  networkErrorText: (error: unknown) => error instanceof Error ? error.message : "网络错误",
}))

const feedback = {
  id: "feedback-1", message_id: "message-1", rating: "negative", reason: "incomplete",
  comment: "缺少步骤", share_context: true, updated_at: "2026-08-16T00:00:00Z",
}
const response = (body: unknown, ok = true, status = 200) => ({ ok, status, json: async () => body }) as Response

describe("feedback API client", () => {
  beforeEach(() => apiFetch.mockReset())

  it("PUT 只发送允许的正向字段", async () => {
    apiFetch.mockResolvedValue(response({ ...feedback, rating: "positive", reason: null, comment: null, share_context: false }))
    await putMessageFeedback("message-1", { rating: "positive", shareContext: false })
    expect(apiFetch).toHaveBeenCalledWith("/api/messages/message-1/feedback", expect.objectContaining({
      method: "PUT", body: JSON.stringify({ rating: "positive", share_context: false }),
    }))
  })

  it("PUT 发送负向原因、可选说明与明确授权", async () => {
    apiFetch.mockResolvedValue(response(feedback))
    await expect(putMessageFeedback("message-1", {
      rating: "negative", reason: "incomplete", comment: " 缺少步骤 ", shareContext: true,
    })).resolves.toMatchObject({ messageId: "message-1", reason: "incomplete", shareContext: true })
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({
      rating: "negative", reason: "incomplete", comment: "缺少步骤", share_context: true,
    })
  })

  it("PUT 在运行时拒绝不在 allowlist 中的原因", async () => {
    await expect(putMessageFeedback("message-1", {
      rating: "negative", reason: "made_up" as never, shareContext: false,
    })).rejects.toThrow("反馈原因无效")
    expect(apiFetch).not.toHaveBeenCalled()
  })

  it("非成功响应转换为现有错误文本", async () => {
    apiFetch.mockResolvedValue(response({ detail: "x" }, false, 422))
    await expect(deleteMessageFeedback("message-1")).rejects.toThrow("后端错误")
  })

  it("GET 解析完整、后端允许的反馈记录", async () => {
    apiFetch.mockResolvedValue(response([feedback]))
    await expect(getThreadFeedback("thread/1")).resolves.toEqual([{
      id: "feedback-1", messageId: "message-1", rating: "negative", reason: "incomplete",
      comment: "缺少步骤", shareContext: true, updatedAt: "2026-08-16T00:00:00Z",
    }])
    expect(apiFetch).toHaveBeenCalledWith("/api/threads/thread%2F1/feedback")
  })

  it("GET 响应不是完整反馈列表时明确报错", async () => {
    apiFetch.mockResolvedValue(response([{ message_id: "bad", rating: "positive" }]))
    await expect(getThreadFeedback("thread-1")).rejects.toThrow("反馈响应格式无效")
  })
})
