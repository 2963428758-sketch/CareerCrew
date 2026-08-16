import { describe, expect, it } from "vitest"
import { notifyError, notifyInfo, subscribeToasts } from "@/lib/toastBus"

describe("toast bus", () => {
  it("publishes typed notices and stops after unsubscribe", () => {
    const received: Array<{ kind: string; text: string }> = []
    const unsubscribe = subscribeToasts((notice) => received.push(notice))

    notifyError("保存反馈失败")
    notifyInfo("已复制")
    unsubscribe()
    notifyError("不应再接收")

    expect(received.map(({ kind, text }) => ({ kind, text }))).toEqual([
      { kind: "error", text: "保存反馈失败" },
      { kind: "info", text: "已复制" },
    ])
  })
})
