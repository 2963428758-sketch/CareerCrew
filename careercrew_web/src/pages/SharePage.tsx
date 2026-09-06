import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import { Briefcase, ShieldCheck } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { apiFetch } from "@/lib/auth"

interface SharedPayload {
  kind?: string
  mask_pii?: boolean
  expires_at?: string
  company?: string
  title?: string
  jd?: string
  city?: string
  salary?: string
  stage?: string
  label?: string
  content?: string
  versions?: Array<{ label: string; content: string; created_at: string }>
}

/** 导师只读分享页：凭令牌访问，无登录；只读，不含任何操作入口。 */
export default function SharePage() {
  const { token = "" } = useParams()
  const [data, setData] = useState<SharedPayload | null>(null)
  const [error, setError] = useState("")

  useEffect(() => {
    apiFetch(`/api/career/share/${encodeURIComponent(token)}`)
      .then(async (resp) => {
        if (!resp.ok) {
          setError(resp.status === 404 ? "分享不存在或已失效" : "加载失败，请稍后重试")
          return
        }
        setData(await resp.json())
      })
      .catch(() => setError("网络连接失败，请稍后重试"))
  }, [token])

  return (
    <div className="min-h-screen bg-shell px-4 py-10">
      <div className="mx-auto w-full max-w-[760px]">
        <header className="mb-6 flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-button-ink text-on-ink">
            <Briefcase className="h-4 w-4" />
          </span>
          <div>
            <h1 className="text-[15px] font-[600] text-ink">CareerCrew · 岗位准备分享</h1>
            <p className="text-[11.5px] text-ink-faint">只读视图 · 候选人主动分享</p>
          </div>
        </header>

        {error ? (
          <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-6 text-center text-[13px] text-ink-soft">
            {error}
          </div>
        ) : !data ? (
          <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-6 text-center text-[13px] text-ink-faint">
            正在加载…
          </div>
        ) : data.kind === "resume_version" ? (
          <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-4">
            <h2 className="text-[15px] font-[600] text-ink">{data.label}</h2>
            <p className="mt-1 text-[11.5px] text-ink-faint">
              简历版本 · 分享截止 {data.expires_at?.slice(0, 10)}
              {data.mask_pii && " · 已隐藏联系方式"}
            </p>
            <pre className="mt-3 whitespace-pre-wrap break-words rounded-[8px] bg-surface-1 p-3 text-[12.5px] leading-relaxed text-ink">
              {data.content}
            </pre>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-4">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-[16px] font-[600] text-ink">
                  {data.company} · {data.title}
                </h2>
                {data.stage && <Badge variant="secondary">{data.stage}</Badge>}
                {data.mask_pii && (
                  <Badge variant="outline" className="text-[10.5px]">
                    <ShieldCheck className="mr-0.5 h-3 w-3" /> 已隐藏联系方式
                  </Badge>
                )}
              </div>
              <p className="mt-1 flex gap-3 text-[12px] text-ink-faint">
                {data.city && <span>{data.city}</span>}
                {data.salary && <span>{data.salary}</span>}
                <span>分享截止 {data.expires_at?.slice(0, 10)}</span>
              </p>
              <p className="mt-3 whitespace-pre-wrap break-words rounded-[8px] bg-surface-1 p-3 text-[12.5px] leading-relaxed text-ink-soft">
                {data.jd}
              </p>
            </div>
            {(data.versions ?? []).map((v) => (
              <div key={v.label + v.created_at} className="rounded-[10px] border border-[var(--border-soft)] bg-card p-4">
                <h3 className="text-[13.5px] font-[560] text-ink">{v.label}</h3>
                <pre className="mt-2 whitespace-pre-wrap break-words text-[12.5px] leading-relaxed text-ink">
                  {v.content}
                </pre>
              </div>
            ))}
          </div>
        )}

        <p className="mt-6 text-center text-[11px] text-ink-faint">
          本页面为临时只读分享，链接过期或被撤销后自动失效。
        </p>
      </div>
    </div>
  )
}
