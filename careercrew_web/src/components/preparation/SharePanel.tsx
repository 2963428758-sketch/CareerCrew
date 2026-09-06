import { useCallback, useEffect, useState } from "react"
import { Copy, Link2Off, Loader2, Share2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { networkErrorText } from "@/lib/errors"
import { createShare, listShares, revokeShare, type ShareInfo } from "@/lib/career"
import { listVersions, type Opportunity, type ResumeVersion } from "@/lib/preparation"

/** 导师只读分享：生成限时链接（整包或单版本），可脱敏、可撤销。 */
export function SharePanel({ opportunity, onToast }: {
  opportunity: Opportunity
  onToast: (msg: string) => void
}) {
  const [shares, setShares] = useState<ShareInfo[]>([])
  const [versions, setVersions] = useState<ResumeVersion[]>([])
  const [versionId, setVersionId] = useState("")
  const [maskPii, setMaskPii] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const reload = useCallback(async () => {
    try {
      const [s, v] = await Promise.all([listShares(), listVersions(opportunity.id)])
      setShares(s.filter((x) => !x.revoked_at))
      setVersions(v)
    } catch (e) {
      setError(networkErrorText(e, "加载分享列表失败"))
    }
  }, [opportunity.id])

  useEffect(() => { void reload() }, [reload])

  const create = async (kind: "opportunity" | "resume_version") => {
    if (busy) return
    setBusy(true)
    setError("")
    try {
      await createShare({
        kind,
        ref_id: kind === "opportunity" ? opportunity.id : versionId,
        expires_days: 7,
        mask_pii: maskPii,
      })
      await reload()
      onToast("分享链接已生成（7 天有效）")
    } catch (e) {
      setError(networkErrorText(e, "创建失败，请稍后重试"))
    } finally {
      setBusy(false)
    }
  }

  const copyLink = async (token: string) => {
    const url = `${window.location.origin}/share/${token}`
    try {
      await navigator.clipboard.writeText(url)
      onToast("链接已复制，发给导师即可（只读）")
    } catch {
      onToast("复制失败：" + url)
    }
  }

  const revoke = async (token: string) => {
    try {
      await revokeShare(token)
      await reload()
      onToast("分享已撤销，链接立即失效")
    } catch (e) {
      onToast(networkErrorText(e, "撤销失败"))
    }
  }

  return (
    <div className="flex flex-col gap-2" data-testid="share-panel">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[13.5px] font-[560] text-ink">导师只读分享</h3>
        <label className="ml-auto flex items-center gap-1 text-[11.5px] text-ink-faint">
          <input type="checkbox" checked={maskPii} onChange={(e) => setMaskPii(e.target.checked)} />
          隐藏联系方式
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={versionId}
          onChange={(e) => setVersionId(e.target.value)}
          aria-label="选择要分享的简历版本"
          className="h-[28px] rounded-[7px] border border-[var(--border-soft)] bg-workspace px-2 text-[12px] text-ink"
        >
          <option value="">选择简历版本…</option>
          {versions.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <Button size="sm" variant="outline" className="h-[26px] text-[12px]"
                disabled={busy} onClick={() => void create("opportunity")}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Share2 className="h-3.5 w-3.5" />}
          分享整包（JD+简历）
        </Button>
        <Button size="sm" variant="outline" className="h-[26px] text-[12px]"
                disabled={busy || !versionId} onClick={() => void create("resume_version")}>
          只分享选定版本
        </Button>
      </div>
      {error && <p className="text-[12px] text-destructive">{error}</p>}
      {shares.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {shares.map((s) => (
            <li key={s.token} className="flex flex-wrap items-center gap-2 rounded-[8px] border border-[var(--border-soft)] bg-card px-2.5 py-1.5 text-[12px]">
              <Badge variant="outline" className="text-[10.5px]">
                {s.kind === "opportunity" ? "整包" : "单版本"}
              </Badge>
              <span className="text-ink-faint">
                截止 {s.expires_at.slice(0, 10)}{s.mask_pii ? " · 已脱敏" : ""}
              </span>
              <button type="button" className="inline-flex items-center gap-0.5 text-[11.5px] text-ink-soft hover:text-ink"
                      onClick={() => void copyLink(s.token)}>
                <Copy className="h-3 w-3" /> 复制链接
              </button>
              <button type="button" aria-label="撤销分享"
                      className="inline-flex items-center gap-0.5 text-[11.5px] text-ink-faint hover:text-destructive"
                      onClick={() => void revoke(s.token)}>
                <Link2Off className="h-3 w-3" /> 撤销
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
