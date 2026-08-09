import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"

/** Markdown 渲染器：把 agent 输出的 markdown 渲染为带样式的 HTML（支持 GFM 表格）。 */
export function MarkdownContent({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("text-sm leading-relaxed", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 className="mb-2 mt-3 text-lg font-bold first:mt-0">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-2 mt-3 text-base font-bold first:mt-0">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-1.5 mt-2.5 text-sm font-semibold first:mt-0">{children}</h3>,
          h4: ({ children }) => <h4 className="mb-1 mt-2 text-sm font-medium first:mt-0">{children}</h4>,
          p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
          ul: ({ children }) => <ul className="mb-2 ml-4 list-disc space-y-1 last:mb-0">{children}</ul>,
          ol: ({ children }) => <ol className="mb-2 ml-4 list-decimal space-y-1 last:mb-0">{children}</ol>,
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
          em: ({ children }) => <em className="italic">{children}</em>,
          del: ({ children }) => <del className="text-muted-foreground line-through">{children}</del>,
          code: ({ children }) => (
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em] text-primary">{children}</code>
          ),
          pre: ({ children }) => (
            <pre className="mb-2 overflow-x-auto rounded-md bg-muted p-3 last:mb-0">{children}</pre>
          ),
          blockquote: ({ children }) => (
            <blockquote className="mb-2 border-l-2 border-primary/40 pl-3 text-muted-foreground last:mb-0">{children}</blockquote>
          ),
          hr: () => <hr className="my-3 border-border" />,
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer" className="text-primary underline underline-offset-2 hover:text-primary/80">
              {children}
            </a>
          ),
          /* 表格：外层包一层 overflow-x-auto 支持横向滚动 */
          table: ({ children }) => (
            <div className="mb-2 overflow-x-auto last:mb-0">
              <table className="w-full border-collapse text-xs">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-muted">{children}</thead>,
          th: ({ children }) => <th className="border border-border px-2.5 py-1.5 text-left font-semibold whitespace-nowrap">{children}</th>,
          td: ({ children }) => <td className="border border-border px-2.5 py-1.5 align-top">{children}</td>,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
