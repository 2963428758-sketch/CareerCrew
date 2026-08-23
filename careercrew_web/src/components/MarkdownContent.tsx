import { memo } from "react"
import ReactMarkdown, { defaultUrlTransform, type Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"

/** 元素映射提为模块常量：避免每次渲染重建对象导致 ReactMarkdown 全量子树重挂。 */
const MARKDOWN_COMPONENTS: Components = {
  h1: ({ children }) => <h1 className="mb-2 mt-4 text-[16px] font-semibold first:mt-0">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-2 mt-4 text-[15px] font-semibold first:mt-0">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-1.5 mt-3 text-[14px] font-medium first:mt-0">{children}</h3>,
  h4: ({ children }) => <h4 className="mb-1 mt-2.5 text-[13px] font-medium first:mt-0">{children}</h4>,
  p: ({ children }) => <p className="mb-2 leading-[1.65] last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-2 ml-4 list-disc space-y-1 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 ml-4 list-decimal space-y-1 last:mb-0">{children}</ol>,
  li: ({ children }) => <li className="leading-[1.65]">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-ink">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  del: ({ children }) => <del className="text-ink-faint line-through">{children}</del>,
  code: ({ children }) => (
    <code className="rounded-[5px] bg-surface-2 px-1.5 py-0.5 font-mono text-[0.85em] text-ink">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="mb-2 overflow-x-auto rounded-[9px] border border-[var(--border-soft)] bg-surface-2 p-3 font-mono text-[12.5px] leading-[1.65] last:mb-0">{children}</pre>
  ),
  blockquote: ({ children }) => (
    <blockquote className="mb-2 border-l-2 border-[var(--border-normal)] pl-3 text-ink-soft last:mb-0">{children}</blockquote>
  ),
  hr: () => <hr className="my-3 border-[var(--border-soft)]" />,
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-primary underline underline-offset-2 hover:opacity-80">
      {children}
    </a>
  ),
  /* 表格：外层包一层 overflow-x-auto 支持横向滚动 */
  table: ({ children }) => (
    <div className="mb-2 overflow-x-auto last:mb-0">
      <table className="w-full border-collapse text-[12.5px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-surface-2">{children}</thead>,
  th: ({ children }) => <th className="border border-[var(--border-soft)] px-2.5 py-1.5 text-left font-medium whitespace-nowrap">{children}</th>,
  td: ({ children }) => <td className="border border-[var(--border-soft)] px-2.5 py-1.5 align-top">{children}</td>,
}

/** Markdown 渲染器：把 agent 输出的 markdown 渲染为带样式的 HTML（支持 GFM 表格）。
 *  Codex 风格：浅色代码块、最弱边框、克制层级。
 *  memo：流式期间父组件每 token 重渲染，children 不变的已完成消息在此 bail out。 */
export const MarkdownContent = memo(function MarkdownContent(
  { children, className }: { children: string; className?: string },
) {
  return (
    <div className={cn("text-[14px] leading-[1.6]", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => (url.startsWith("blob:") ? url : defaultUrlTransform(url))}
        components={MARKDOWN_COMPONENTS}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
})
