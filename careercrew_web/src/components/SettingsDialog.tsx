import { useEffect } from "react"
import { X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { DataSettingsContent } from "@/pages/DataPage"

/** 侧边栏右下角"设置"弹窗：承载数据看板内容（画像 / 记忆 / 记忆设置）。 */
export function SettingsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      window.removeEventListener("keydown", onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-6"
      onClick={onClose}
    >
      <div
        className="flex h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border bg-background shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex h-14 shrink-0 items-center justify-between border-b px-5">
          <h2 className="font-display text-base font-semibold">设置</h2>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose} title="关闭">
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          <DataSettingsContent />
        </div>
      </div>
    </div>
  )
}
