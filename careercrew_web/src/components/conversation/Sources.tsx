import { useState } from "react"
import { ChevronDown, ChevronUp, FileText } from "lucide-react"
import type { KnowledgeSource } from "@/types"

/** 引用来源：默认折叠为「N sources」，点击展开编号列表（12px 弱化样式）。 */
export function Sources({ sources }: { sources: KnowledgeSource[] }) {
  const [open, setOpen] = useState(false)
  if (!sources.length) return null
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-[12px] text-ink-faint transition-colors duration-100 hover:text-ink"
      >
        {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        {sources.length} 个来源
      </button>
      {open && (
        <ul className="mt-1.5 flex flex-col gap-0.5">
          {sources.map((s, i) => (
            <li key={`${s.doc}-${i}`} className="flex items-start gap-1.5 text-[12px] leading-[1.5] text-ink-soft">
              <span className="mt-px shrink-0 font-medium text-ink-faint">[{i + 1}]</span>
              <span className="flex min-w-0 items-center gap-1">
                <FileText className="h-3 w-3 shrink-0 text-ink-faint" />
                <span className="truncate">{s.doc || s.source}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
