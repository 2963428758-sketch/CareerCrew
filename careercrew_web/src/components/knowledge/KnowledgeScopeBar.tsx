import { KB_CATEGORIES, KB_CATEGORY_LABELS, KB_SCOPE, KB_SCOPE_LABELS } from "@/types"
import { Chip } from "./KnowledgeAssistant"

export type KnowledgeScope = "all" | "public" | "private"

/** Composer 头部的「范围 × 分类」双维度选择条（正交：可同时选中，如「公共库 · 面试题」）。 */
export function KnowledgeScopeBar({ scope, category, onScope, onCategory }: {
  scope: KnowledgeScope
  category: string
  onScope: (next: KnowledgeScope) => void
  onCategory: (id: string) => void
}) {
  return (
    <div className="mb-2 flex flex-wrap items-center gap-1.5">
      <span className="mr-0.5 text-[11px] font-medium text-ink-faint">范围</span>
      {KB_SCOPE.map((s) => (
        <Chip key={s.id} active={scope === s.id} onClick={() => onScope(s.id as KnowledgeScope)}>
          {s.label}
        </Chip>
      ))}
      <span aria-hidden className="mx-1 h-3 w-px bg-[var(--border-normal)]" />
      <span className="mr-0.5 text-[11px] font-medium text-ink-faint">分类</span>
      {KB_CATEGORIES.map((c) => (
        <Chip key={c.id || "all"} active={category === c.id} onClick={() => onCategory(c.id)}>
          {c.label}
        </Chip>
      ))}
      <span className="ml-auto text-[11px] text-ink-faint">
        当前：{KB_SCOPE_LABELS[scope]} · {KB_CATEGORY_LABELS[category] ?? "全部分类"}
      </span>
    </div>
  )
}
