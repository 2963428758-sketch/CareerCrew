import { apiFetch } from "@/lib/auth"
import { apiErrorText, networkErrorText } from "@/lib/errors"

export const NEGATIVE_FEEDBACK_REASONS = [
  "incorrect", "not_relevant", "incomplete", "too_verbose", "unclear",
  "instruction_failure", "tool_failure", "citation_failure", "other",
] as const

export type NegativeFeedbackReason = typeof NEGATIVE_FEEDBACK_REASONS[number]
export type FeedbackRating = "positive" | "negative"

export interface PersistedFeedback {
  id: string
  messageId: string
  rating: FeedbackRating
  reason?: NegativeFeedbackReason
  comment?: string
  shareContext: boolean
  updatedAt?: string
}

export interface FeedbackRequest {
  rating: FeedbackRating
  reason?: NegativeFeedbackReason
  comment?: string
  shareContext: boolean
}

type FeedbackResponse = {
  id?: unknown
  message_id?: unknown
  rating?: unknown
  reason?: unknown
  comment?: unknown
  share_context?: unknown
  updated_at?: unknown
}

const isReason = (value: unknown): value is NegativeFeedbackReason =>
  typeof value === "string" && (NEGATIVE_FEEDBACK_REASONS as readonly string[]).includes(value)

function parseFeedback(row: unknown): PersistedFeedback | null {
  if (!row || typeof row !== "object") return null
  const feedback = row as FeedbackResponse
  if (typeof feedback.id !== "string" || typeof feedback.message_id !== "string") return null
  if (feedback.rating !== "positive" && feedback.rating !== "negative") return null
  if (feedback.reason !== undefined && feedback.reason !== null && !isReason(feedback.reason)) return null
  return {
    id: feedback.id,
    messageId: feedback.message_id,
    rating: feedback.rating,
    ...(isReason(feedback.reason) ? { reason: feedback.reason } : {}),
    ...(typeof feedback.comment === "string" && feedback.comment ? { comment: feedback.comment } : {}),
    shareContext: feedback.share_context === true,
    ...(typeof feedback.updated_at === "string" ? { updatedAt: feedback.updated_at } : {}),
  }
}

function toBody(request: FeedbackRequest) {
  if (request.rating === "negative" && !request.reason) throw new Error("负面反馈必须选择有效原因")
  if (request.rating === "positive" && request.reason) throw new Error("正面反馈不能包含负面原因")
  return {
    rating: request.rating,
    ...(request.reason ? { reason: request.reason } : {}),
    ...(request.comment?.trim() ? { comment: request.comment.trim() } : {}),
    share_context: request.shareContext,
  }
}

export async function putMessageFeedback(messageId: string, request: FeedbackRequest): Promise<PersistedFeedback> {
  try {
    const response = await apiFetch(`/api/messages/${encodeURIComponent(messageId)}/feedback`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toBody(request)),
    })
    if (!response.ok) throw new Error(await apiErrorText(response, "保存反馈失败，请重试"))
    const feedback = parseFeedback(await response.json())
    if (!feedback || feedback.messageId !== messageId) throw new Error("反馈响应格式无效，请刷新后重试")
    return feedback
  } catch (error) {
    throw new Error(networkErrorText(error, "保存反馈失败，请检查网络后重试"))
  }
}

export async function deleteMessageFeedback(messageId: string): Promise<void> {
  try {
    const response = await apiFetch(`/api/messages/${encodeURIComponent(messageId)}/feedback`, { method: "DELETE" })
    if (!response.ok) throw new Error(await apiErrorText(response, "撤销反馈失败，请重试"))
  } catch (error) {
    throw new Error(networkErrorText(error, "撤销反馈失败，请检查网络后重试"))
  }
}

export async function getThreadFeedback(threadId: string): Promise<PersistedFeedback[]> {
  try {
    const response = await apiFetch(`/api/threads/${encodeURIComponent(threadId)}/feedback`)
    if (!response.ok) throw new Error(await apiErrorText(response, "加载反馈失败，请重试"))
    const rows: unknown = await response.json()
    return Array.isArray(rows) ? rows.map(parseFeedback).filter((row): row is PersistedFeedback => row !== null) : []
  } catch (error) {
    throw new Error(networkErrorText(error, "加载反馈失败，请检查网络后重试"))
  }
}
