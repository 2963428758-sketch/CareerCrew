import { describe, expect, it } from "vitest"
import { renderToStaticMarkup } from "react-dom/server"
import ReactMarkdown, { defaultUrlTransform } from "react-markdown"
import { MarkdownContent } from "@/components/MarkdownContent"

const BLOB = "blob:http://localhost:5173/550e8400-e29b-41d4-a716-446655440000"

describe("MarkdownContent blob URL", () => {
  it("renders blob: image src unchanged", () => {
    const html = renderToStaticMarkup(<MarkdownContent>{`![图](${BLOB})`}</MarkdownContent>)
    expect(html).toContain(`src="${BLOB}"`)
  })

  it("documents upstream default strips blob:", () => {
    const html = renderToStaticMarkup(<ReactMarkdown>{`![图](${BLOB})`}</ReactMarkdown>)
    expect(html).not.toContain(BLOB) // 上游白名单不含 blob，src 被置空
  })

  it("keeps defaultUrlTransform for other URLs", () => {
    expect(defaultUrlTransform("javascript:alert(1)")).toBe("")
    expect(defaultUrlTransform("https://example.com/a")).toBe("https://example.com/a")
  })
})
