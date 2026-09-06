import { useEffect, useMemo, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { ArrowLeft, Briefcase, Plus, RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ConfirmDialog } from "@/components/ui/ConfirmDialog"
import { EmptyState } from "@/components/workspace/EmptyState"
import { ToastBubble } from "@/components/conversation/ToastBubble"
import { useToast } from "@/hooks/useToast"
import { networkErrorText } from "@/lib/errors"
import {
  createOpportunity,
  deleteOpportunity,
  listOpportunities,
  updateOpportunity,
  type Opportunity,
  type OpportunityInput,
} from "@/lib/preparation"
import { isSafeHttpUrl } from "@/lib/preparation"
import { OpportunityCard } from "@/components/preparation/OpportunityCard"
import { OpportunityForm } from "@/components/preparation/OpportunityForm"
import { ResumeWorkspace } from "@/components/preparation/ResumeWorkspace"
import { GapAnalysisPanel } from "@/components/preparation/GapAnalysisPanel"
import { OpportunityTimeline } from "@/components/preparation/OpportunityTimeline"
import { JobToolsPanel } from "@/components/preparation/JobToolsPanel"
import { CollectorBookmarklet } from "@/components/preparation/CollectorBookmarklet"
import { SharePanel } from "@/components/preparation/SharePanel"

/** 岗位准备工作台：收藏岗位 → 关联简历版本 → 一键带入简历定制 / 模拟面试。 */
export default function PreparationPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [opportunities, setOpportunities] = useState<Opportunity[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")
  const [keyword, setKeyword] = useState("")
  const [formMode, setFormMode] = useState<"create" | "edit" | null>(null)
  const [formSaving, setFormSaving] = useState(false)
  const [formError, setFormError] = useState("")
  const [deleteTarget, setDeleteTarget] = useState<Opportunity | null>(null)
  const [deleting, setDeleting] = useState(false)
  const { toast, showToast } = useToast()

  const selectedId = searchParams.get("opportunity")
  const selected = useMemo(
    () => opportunities.find((o) => o.id === selectedId) ?? null,
    [opportunities, selectedId],
  )
  // 通用岗位采集器：书签脚本以 ?collect=1&url=&title=&jd= 打开本页，预填录入表单
  const collectDraft = useMemo(() => {
    if (searchParams.get("collect") !== "1") return null
    return {
      url: searchParams.get("url") || "",
      title: searchParams.get("title") || "",
      jd: searchParams.get("jd") || "",
    }
  }, [searchParams])
  const [collectConsumed, setCollectConsumed] = useState(false)

  useEffect(() => {
    if (!collectDraft || collectConsumed || loading) return
    setCollectConsumed(true)
    select(null)
    setFormMode("create")
  }, [collectDraft, collectConsumed, loading])

  const reload = async () => {
    setLoading(true)
    setLoadError("")
    try {
      const rows = await listOpportunities()
      setOpportunities(rows)
    } catch (e) {
      setLoadError(networkErrorText(e, "岗位列表加载失败，请稍后重试"))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void reload()
  }, [])

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    if (!kw) return opportunities
    return opportunities.filter((o) =>
      [o.company, o.title, o.city, o.source].some((v) => v.toLowerCase().includes(kw)))
  }, [opportunities, keyword])

  const select = (id: string | null) => {
    setFormMode(null)
    setFormError("")
    setSearchParams(id ? { opportunity: id } : {}, { replace: false })
  }

  const handleCreate = async (input: OpportunityInput) => {
    setFormSaving(true)
    setFormError("")
    try {
      const saved = await createOpportunity(input)
      setOpportunities((prev) => [saved, ...prev])
      setFormMode(null)
      select(saved.id)
      showToast("岗位已保存")
    } catch (e) {
      setFormError(e instanceof Error ? e.message : networkErrorText(e, "保存失败，请稍后重试"))
    } finally {
      setFormSaving(false)
    }
  }

  const handleUpdate = async (input: OpportunityInput) => {
    if (!selected) return
    setFormSaving(true)
    setFormError("")
    try {
      const saved = await updateOpportunity(selected.id, input)
      setOpportunities((prev) => prev.map((o) => (o.id === saved.id ? saved : o)))
      setFormMode(null)
      showToast("岗位已更新")
    } catch (e) {
      setFormError(e instanceof Error ? e.message : networkErrorText(e, "更新失败，请稍后重试"))
    } finally {
      setFormSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteOpportunity(deleteTarget.id)
      setOpportunities((prev) => prev.filter((o) => o.id !== deleteTarget.id))
      if (selectedId === deleteTarget.id) select(null)
      showToast("岗位及关联版本、会话已删除")
    } catch (e) {
      showToast(e instanceof Error ? e.message : networkErrorText(e, "删除失败，请稍后重试"))
    } finally {
      setDeleting(false)
      setDeleteTarget(null)
    }
  }

  /** 从现有简历库载入解析文本作为原文。 */
  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between gap-3 border-b border-[var(--border-soft)] px-4 py-3 md:px-6">
        <div className="flex items-center gap-2.5">
          {selected && (
            <Button
              variant="ghost"
              size="icon"
              className="h-[30px] w-[30px] md:hidden"
              aria-label="返回岗位列表"
              onClick={() => select(null)}
            >
              <ArrowLeft className="h-4 w-4" />
            </Button>
          )}
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-button-ink text-on-ink">
            <Briefcase className="h-4 w-4" />
          </span>
          <div>
            <h1 className="text-[15px] font-[600] text-ink">岗位准备</h1>
            <p className="text-[11.5px] text-ink-faint">收藏目标岗位，关联简历版本，一键带入简历定制与模拟面试</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            className="h-[30px] w-[30px]"
            aria-label="刷新列表"
            onClick={() => void reload()}
          >
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Button size="sm" className="h-[30px] text-[12.5px]" onClick={() => { select(null); setFormMode("create") }}>
            <Plus className="h-4 w-4" /> 手动录入岗位
          </Button>
        </div>
      </header>

      <div className="grid flex-1 gap-0 overflow-hidden md:grid-cols-[340px_1fr]">
        {/* 左列：岗位列表 */}
        <aside
          className={
            "flex flex-col gap-2.5 overflow-y-auto border-[var(--border-soft)] p-4 md:border-r " +
            (selected && !formMode ? "hidden md:flex" : "flex")
          }
        >
          <Input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索公司 / 岗位 / 城市"
            className="h-[32px]"
          />
          <details className="rounded-[8px] border border-[var(--border-soft)] bg-card px-2.5 py-1.5 text-[11.5px] text-ink-faint">
            <summary className="cursor-pointer select-none">通用岗位采集器（任意招聘网站）</summary>
            <p className="mt-1.5 leading-relaxed">
              在招聘网站页面上选中 JD 文本，点击书签即可跳回本页预填录入。
              把下面的代码新建为书签（网址栏粘贴整段）：
            </p>
            <CollectorBookmarklet />
          </details>
          {loading ? (
            <p className="text-[12.5px] text-ink-faint">正在加载岗位…</p>
          ) : loadError ? (
            <div className="text-[12.5px] text-destructive">
              {loadError}
              <Button variant="outline" size="sm" className="ml-2 h-[26px] text-[12px]" onClick={() => void reload()}>
                重试
              </Button>
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState
              title={keyword ? "没有匹配的岗位" : "还没有收藏的岗位"}
              description={keyword ? "换个关键词试试" : "在职位匹配结果中收藏，或点击右上角手动录入"}
            />
          ) : (
            filtered.map((item) => (
              <OpportunityCard
                key={item.id}
                item={item}
                selected={item.id === selectedId}
                onSelect={() => select(item.id)}
                onDelete={() => setDeleteTarget(item)}
              />
            ))
          )}
        </aside>

        {/* 右列：详情 / 表单 */}
        <section
          className={
            "flex flex-col gap-4 overflow-y-auto p-4 md:p-6 " +
            (selected || formMode ? "flex" : "hidden md:flex")
          }
        >
          {formMode === "create" && (
            <div>
              <h2 className="mb-3 text-[13.5px] font-[560] text-ink">手动录入岗位</h2>
              <OpportunityForm
                draft={collectDraft}
                saving={formSaving}
                error={formError}
                onSubmit={handleCreate}
                onCancel={() => { setFormMode(null); setFormError("") }}
              />
            </div>
          )}
          {formMode === "edit" && selected && (
            <div>
              <h2 className="mb-3 text-[13.5px] font-[560] text-ink">编辑岗位</h2>
              <OpportunityForm
                initial={selected}
                saving={formSaving}
                error={formError}
                onSubmit={handleUpdate}
                onCancel={() => { setFormMode(null); setFormError("") }}
              />
            </div>
          )}
          {!formMode && selected && (
            <>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <h2 className="truncate text-[16px] font-[600] text-ink">
                    {selected.company} · {selected.title}
                  </h2>
                  <p className="mt-0.5 flex flex-wrap gap-x-3 text-[12px] text-ink-faint">
                    {selected.city && <span>{selected.city}</span>}
                    {selected.salary && <span>{selected.salary}</span>}
                    {selected.source && <span>来源：{selected.source}</span>}
                    {isSafeHttpUrl(selected.url) && (
                      <a
                        href={selected.url}
                        target="_blank"
                        rel="noopener noreferrer nofollow"
                        className="hover:text-ink"
                      >
                        打开岗位链接
                      </a>
                    )}
                  </p>
                </div>
                <Button variant="outline" size="sm" className="h-[26px] text-[12px]" onClick={() => setFormMode("edit")}>
                  编辑岗位
                </Button>
              </div>
              <div>
                <h3 className="mb-1 text-[13.5px] font-[560] text-ink">JD 快照</h3>
                <p className="whitespace-pre-wrap break-words rounded-[10px] border border-[var(--border-soft)] bg-card p-3 text-[12.5px] leading-relaxed text-ink-soft">
                  {selected.jd}
                </p>
              </div>
              <ResumeWorkspace key={selected.id} opportunity={selected} onToast={showToast} />
              <div className="border-t border-[var(--border-soft)] pt-3">
                <JobToolsPanel opportunity={selected} onToast={showToast} />
              </div>
              <div className="border-t border-[var(--border-soft)] pt-3">
                <GapAnalysisPanel opportunityId={selected.id} onToast={showToast} />
              </div>
              <div className="border-t border-[var(--border-soft)] pt-3">
                <OpportunityTimeline opportunityId={selected.id} />
              </div>
              <div className="border-t border-[var(--border-soft)] pt-3">
                <SharePanel opportunity={selected} onToast={showToast} />
              </div>
            </>
          )}
          {!formMode && !selected && (
            <div className="flex h-full items-center justify-center">
              <EmptyState
                title="选择或新建一个岗位"
                description="每个岗位保存自己的 JD 快照、简历版本与准备会话"
              />
            </div>
          )}
        </section>
      </div>
      <ToastBubble message={toast} />
      <ConfirmDialog
        open={deleteTarget !== null}
        title="删除岗位？"
        message={`「${deleteTarget?.company ?? ""} · ${deleteTarget?.title ?? ""}」及其全部简历版本与准备会话将被删除，不可恢复。`}
        confirmLabel="删除岗位"
        pending={deleting}
        pendingLabel="删除中…"
        closeOnConfirm={false}
        onConfirm={() => void handleDelete()}
        onClose={() => { if (!deleting) setDeleteTarget(null) }}
      />
    </div>
  )
}
