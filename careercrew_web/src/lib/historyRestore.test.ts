import { beforeEach, describe, expect, it, vi } from "vitest"
import {
  parseMemoryEntries,
  parseThreadMessages,
  restoreHistory,
} from "@/lib/historyRestore"

const apiFetch = vi.fn()
vi.mock("@/lib/auth", () => ({ apiFetch: (...a: unknown[]) => apiFetch(...a) }))

describe("historyRestore", () => {
  beforeEach(() => {
    apiFetch.mockReset()
  })

  describe("parseThreadMessages", () => {
    it("解析 messages 端点行，携带稳定 ID + metadata", () => {
      const rows = [
        {
          id: "m-user-1", turn_id: "t-1", role: "user", content: "你好",
          run_id: null, metadata: null,
        },
        {
          id: "m-asst-1", turn_id: "t-1", role: "assistant", content: "回答",
          run_id: "r-1", metadata: { sources: [{ doc: "note" }] },
        },
      ]
      const msgs = parseThreadMessages(rows)
      expect(msgs).toHaveLength(2)
      expect(msgs[0]).toMatchObject({ role: "user", content: "你好", messageId: "m-user-1", turnId: "t-1" })
      expect(msgs[1]).toMatchObject({
        role: "assistant", content: "回答", messageId: "m-asst-1",
        turnId: "t-1", runId: "r-1",
      })
      expect(msgs[1].metadata).toEqual({ sources: [{ doc: "note" }] })
    })

    it("跳过无内容或非法 role 的行", () => {
      const msgs = parseThreadMessages([
        { id: "x", turn_id: "t", role: "system", content: "hmm" },
        { id: "y", turn_id: "t", role: "assistant", content: "" },
        null,
      ])
      expect(msgs).toHaveLength(0)
    })
  })

  describe("parseMemoryEntries", () => {
    it("解析 memory 端点 episodic 条目（无稳定 ID）", () => {
      const entries = [
        { type: "user_message", content: "问题" },
        { type: "agent_response", content: "答案", sources: [{ doc: "d" }] },
        { type: "fact", content: "无关" },
      ]
      const msgs = parseMemoryEntries(entries)
      expect(msgs).toHaveLength(2)
      expect(msgs[0]).toMatchObject({ role: "user", content: "问题" })
      expect(msgs[0].messageId).toBeUndefined()
      expect(msgs[1]).toMatchObject({ role: "assistant", content: "答案" })
    })
  })

  describe("restoreHistory", () => {
    it("messages 端点非空 → 用稳定 ID 消息，不回退 memory", async () => {
      apiFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => [
          { id: "m1", turn_id: "t1", role: "user", content: "q", run_id: null, metadata: null },
          { id: "m2", turn_id: "t1", role: "assistant", content: "a", run_id: "r1", metadata: null },
        ],
      })
      const msgs = await restoreHistory("tid-1")
      expect(msgs).toHaveLength(2)
      expect(msgs[1].messageId).toBe("m2")
      // messages 非空则不再请求 memory
      expect(apiFetch).toHaveBeenCalledTimes(1)
      expect(apiFetch).toHaveBeenCalledWith("/api/threads/tid-1/messages")
    })

    it("messages 端点空 → 回退 memory 端点", async () => {
      apiFetch.mockResolvedValueOnce({ ok: true, json: async () => [] })
      apiFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => [{ type: "user_message", content: "legacy q" }],
      })
      const msgs = await restoreHistory("tid-2")
      expect(msgs).toHaveLength(1)
      expect(msgs[0]).toMatchObject({ role: "user", content: "legacy q" })
      expect(msgs[0].messageId).toBeUndefined()
      expect(apiFetch).toHaveBeenCalledTimes(2)
    })

    it("messages 端点 404/失败 → 回退 memory; memory 也失败 → 空数组", async () => {
      apiFetch.mockResolvedValueOnce({ ok: false, status: 404, json: async () => ({}) })
      apiFetch.mockRejectedValueOnce(new Error("network"))
      const msgs = await restoreHistory("tid-3")
      expect(msgs).toEqual([])
    })
  })
})
