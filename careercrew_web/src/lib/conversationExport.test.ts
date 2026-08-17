import { describe, expect, it, vi } from "vitest"
import { buildMarkdown, buildJson, downloadBlob, type ExportMessage } from "@/lib/conversationExport"

const TITLE = "求职咨询"

const MESSAGES: ExportMessage[] = [
  { role: "user", content: "帮我找大模型岗位" },
  { role: "assistant", content: "推荐字节/阿里", sources: [{ doc: "note", source: "data/note.md" }] },
]

describe("conversationExport — 纯函数", () => {
  it("buildMarkdown 含标题/User/Assistant/Sources", () => {
    const md = buildMarkdown(TITLE, MESSAGES)
    expect(md).toContain("# 求职咨询")
    expect(md).toContain("## User")
    expect(md).toContain("帮我找大模型岗位")
    expect(md).toContain("## Assistant")
    expect(md).toContain("### Sources")
    expect(md).toContain("- note")
  })

  it("buildMarkdown 跳过非 user/assistant 角色", () => {
    const msgs = [...MESSAGES, { role: "system", content: "SYSTEM PROMPT" }]
    expect(buildMarkdown(TITLE, msgs as ExportMessage[])).not.toContain("SYSTEM PROMPT")
  })

  it("buildJson 含 thread/messages/sources 且不含敏感字段", () => {
    const body = buildJson(TITLE, MESSAGES)
    expect(body.thread.title).toBe(TITLE)
    expect(body.messages[0].role).toBe("user")
    expect(body.messages[1].sources?.[0].doc).toBe("note")
    const text = JSON.stringify(body)
    expect(text).not.toContain("token")
    expect(text).not.toContain("api_key")
  })

  it("downloadBlob 触发 Blob 下载并生成正确文件名", () => {
    const createObjectURL = vi.fn(() => "blob:mock")
    const revokeObjectURL = vi.fn()
    const anchor = {
      href: "",
      download: "",
      click: vi.fn(),
    }
    const appendChild = vi.fn()
    const removeChild = vi.fn()
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL })
    vi.stubGlobal("document", {
      createElement: vi.fn(() => anchor),
      body: { appendChild, removeChild },
    })

    downloadBlob("# 标题", "text/markdown", "求职咨询.md")

    expect(createObjectURL).toHaveBeenCalledOnce()
    expect(appendChild).toHaveBeenCalledOnce()
    expect(removeChild).toHaveBeenCalledOnce()
    expect(anchor.click).toHaveBeenCalledOnce()
    expect(anchor.download).toBe("求职咨询.md")
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock")
    vi.unstubAllGlobals()
  })
})
