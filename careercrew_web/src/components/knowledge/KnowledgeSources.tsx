import { useState } from "react"
import { ChevronDown } from "lucide-react"
import { Tooltip } from "@/components/ui/tooltip"
import { KB_CATEGORY_LABELS, type KnowledgeSource } from "@/types"
import { cn } from "@/lib/utils"
import { useAuthenticatedImages } from "./useAuthenticatedImages"

/** 回答下方的「数据来源」折叠列表：点击展开原文片段与配图。 */
export function SourceList({ sources, onPreview }: { sources: KnowledgeSource[]; onPreview: (url: string) => void }) {
  const [open, setOpen] = useState<Set<number>>(new Set())
  const [failedImgs, setFailedImgs] = useState<Set<string>>(new Set())
  const images = useAuthenticatedImages(sources.map((source) => source.image_path))

  const toggle = (i: number) => {
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  }

  return (
    <div className="mt-3 space-y-1.5 border-t border-[var(--border-soft)] pt-2.5">
      <p className="text-[11px] font-medium text-ink-faint">
        数据来源（{sources.length}）· 点击查看原文
      </p>
      {sources.map((s, i) => {
        const expanded = open.has(i)
        const name = s.doc || s.source.split(/[\\/]/).pop() || `来源 ${i + 1}`
        // 原始相关度百分比（0-1 -> 0-100%），不做相对归一化，避免低分片段显示成 100%
        const pct = Math.round(s.score * 100)
        const imgPath = s.image_path
        const image = imgPath ? images[imgPath] : undefined
        return (
          <div key={`${s.doc}-${i}`} className="overflow-hidden rounded-[8px] border border-[var(--border-soft)] bg-surface-2">
            <button
              onClick={() => toggle(i)}
              className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left transition-colors duration-100 hover:bg-[var(--hover)]"
            >
              <span className="text-[10.5px] font-medium text-ink-faint">[{i + 1}]</span>
              <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-ink">{name}</span>
              {s.category && (
                <span className="shrink-0 rounded-[5px] bg-surface-3 px-1.5 py-0.5 text-[10px] text-ink-soft">
                  {KB_CATEGORY_LABELS[s.category] ?? s.category}
                </span>
              )}
              {s.used_image ? (
                <span className="shrink-0 rounded-[5px] bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                  已读图
                </span>
              ) : (
                <span className="shrink-0 text-[10px] text-ink-faint">相关度 {pct}%</span>
              )}
              <ChevronDown className={cn("h-3 w-3 shrink-0 text-ink-faint transition-transform duration-100", expanded && "rotate-180")} />
            </button>
            {expanded && (
              <div className="border-t border-[var(--border-soft)] bg-workspace px-3 py-2">
                {imgPath && (
                  failedImgs.has(imgPath) || image?.status === "error" ? (
                    <p className="mb-1.5 truncate text-[10.5px] text-ink-faint">
                      图片：{imgPath.replace(/\\/g, "/")}
                    </p>
                  ) : image?.status !== "ready" || !image.url ? (
                    <p className="mb-1.5 text-[10.5px] text-ink-faint">图片加载中…</p>
                  ) : (
                    <Tooltip label="点击查看大图（滚轮缩放）">
                      <button
                        onClick={() => onPreview(image.url!)}
                        className="mb-2 block w-full"
                      >
                        <img
                          src={image.url}
                          alt={name}
                          className="max-h-44 w-full rounded-[7px] bg-surface-2 object-contain transition-opacity duration-100 hover:opacity-90"
                          onError={() => setFailedImgs((prev) => new Set(prev).add(imgPath))}
                        />
                      </button>
                    </Tooltip>
                  )
                )}
                <p className="whitespace-pre-wrap text-[12px] leading-relaxed text-ink-soft">{s.text}</p>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
