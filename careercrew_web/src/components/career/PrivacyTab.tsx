import { CareerSearch } from "@/components/career/CareerSearch"
import { useState } from "react"
import { Download } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/ConfirmDialog"
import { networkErrorText } from "@/lib/errors"
import { todayStr } from "./dates"

export function PrivacyTab({ onToast }: { onToast: (m: string) => void }) {
  const [confirmPurge, setConfirmPurge] = useState(false)

  const doExport = async () => {
    try {
      const { exportPrivacyData } = await import("@/lib/career")
      const data = await exportPrivacyData()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `careercrew-数据导出-${todayStr()}.json`
      a.click()
      URL.revokeObjectURL(url)
      onToast("个人资料已导出")
    } catch (e) { onToast(networkErrorText(e, "导出失败，请稍后重试")) }
  }

  return (
    <div className="flex flex-col gap-3 text-[13px]">
      <CareerSearch onToast={onToast} />
      <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3">
        <p className="font-[560] text-ink">导出我的全部数据</p>
        <p className="mt-1 text-[12px] text-ink-faint">包含岗位、版本、素材、任务、HR 记录、Offer 与真实面试复盘（JSON）。</p>
        <Button size="sm" variant="outline" className="mt-2 h-[28px] text-[12.5px]" onClick={() => void doExport()}>
          <Download className="h-4 w-4" /> 导出 JSON
        </Button>
      </div>
      <div className="rounded-[10px] border border-destructive/40 bg-card p-3">
        <p className="font-[560] text-destructive">删除全部求职数据</p>
        <p className="mt-1 text-[12px] text-ink-faint">
          删除岗位准备（含简历版本与准备会话）与求职跟进数据；不影响对话历史与简历库。
        </p>
        <Button size="sm" variant="destructive" className="mt-2 h-[28px] text-[12.5px]" onClick={() => setConfirmPurge(true)}>
          删除我的全部求职数据
        </Button>
      </div>
      <ConfirmDialog
        open={confirmPurge}
        title="确认删除全部求职数据？"
        message="岗位、简历版本、准备会话、素材、任务、HR 记录、Offer 与复盘都会被删除，不可恢复。"
        confirmLabel="全部删除"
        onConfirm={async () => {
          try {
            const { purgePrivacyData } = await import("@/lib/career")
            const result = await purgePrivacyData()
            onToast(`已删除 ${Object.values(result.deleted || {}).reduce((a, b) => a + b, 0)} 条记录`)
          } catch (e) { onToast(networkErrorText(e, "删除失败，请稍后重试")) }
          setConfirmPurge(false)
        }}
        onClose={() => setConfirmPurge(false)}
      />
    </div>
  )
}
