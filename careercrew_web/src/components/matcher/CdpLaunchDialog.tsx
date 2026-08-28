import { useEffect, useState } from "react"
import { Play, Copy, Check, RefreshCw, CheckCircle2, AlertCircle, ExternalLink, X, Terminal, Globe } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { apiFetch } from "@/lib/auth"
import type { CdpStatus } from "./CdpStatusBar"

interface CdpLaunchDialogProps {
  open: boolean
  onClose: () => void
  status: CdpStatus | null
  onStatusUpdate: (status: CdpStatus) => void
  onToast?: (msg: string) => void
}

export function CdpLaunchDialog({
  open,
  onClose,
  status,
  onStatusUpdate,
  onToast,
}: CdpLaunchDialogProps) {
  const [copied, setCopied] = useState(false)
  const [checking, setChecking] = useState(false)
  const [launching, setLaunching] = useState(false)

  const checkStatus = async () => {
    setChecking(true)
    try {
      const res = await apiFetch("/api/browser/cdp-status")
      if (res.ok) {
        const data = (await res.json()) as CdpStatus
        onStatusUpdate(data)
      }
    } catch {
      // 保持旧状态
    } finally {
      setChecking(false)
    }
  }

  const handleLaunch = async () => {
    setLaunching(true)
    try {
      const res = await apiFetch("/api/browser/launch-cdp", { method: "POST" })
      const data = await res.json()
      onToast?.(data.message || "已尝试启动 Chrome 采集器")
      // 轮询几次检测端口
      let count = 0
      const timer = setInterval(async () => {
        count += 1
        try {
          const checkRes = await apiFetch("/api/browser/cdp-status")
          if (checkRes.ok) {
            const checkData = (await checkRes.json()) as CdpStatus
            onStatusUpdate(checkData)
            if (checkData.connected || count >= 5) {
              clearInterval(timer)
              setLaunching(false)
            }
          }
        } catch {
          if (count >= 5) {
            clearInterval(timer)
            setLaunching(false)
          }
        }
      }, 1500)
    } catch {
      onToast?.("启动请求失败，请手动运行脚本")
      setLaunching(false)
    }
  }

  const handleCopy = () => {
    const cmd = status?.command || "powershell -ExecutionPolicy Bypass -File scripts/start_chrome_cdp.ps1"
    navigator.clipboard.writeText(cmd).then(() => {
      setCopied(true)
      onToast?.("已复制启动命令到剪贴板")
      setTimeout(() => setCopied(false), 2000)
    })
  }

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  if (!open) return null

  const isConnected = Boolean(status?.connected)

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 p-4 backdrop-blur-[2px]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="stream-fade-in relative flex w-full max-w-[560px] flex-col rounded-[14px] border border-border bg-card p-6 shadow-2xl">
        {/* 顶部标题与关闭 */}
        <div className="flex items-start justify-between gap-3 border-b border-border/60 pb-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Globe className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-foreground">Chrome CDP 调试采集器</h3>
              <p className="text-xs text-muted-foreground">接管已登录的本地 Chrome，防封且支持 Boss直聘 与 猎聘 实时抓取</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* 状态徽章与详情 */}
        <div className="my-4 flex flex-col gap-3">
          <div className={`flex items-center justify-between rounded-lg border p-3 ${isConnected ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300"}`}>
            <div className="flex items-center gap-2">
              {isConnected ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : <AlertCircle className="h-4 w-4 text-amber-500" />}
              <span className="text-xs font-semibold">{isConnected ? "调试服务已连通 (9222 端口可用)" : "调试服务未连通 (127.0.0.1:9222)"}</span>
            </div>
            <Button size="sm" variant="ghost" className="h-6 gap-1 px-2 text-[11px]" onClick={checkStatus} disabled={checking}>
              <RefreshCw className={`h-3 w-3 ${checking ? "animate-spin" : ""}`} />
              检测连接
            </Button>
          </div>

          {isConnected ? (
            <div className="flex flex-col gap-3 rounded-lg border border-border/80 bg-muted/20 p-4">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">已开启标签页检测：</span>
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className={status?.boss_opened ? "border-emerald-500/40 text-emerald-600 dark:text-emerald-400" : "text-muted-foreground"}>
                    Boss直聘 {status?.boss_opened ? "✓ 已打开" : "待打开"}
                  </Badge>
                  <Badge variant="outline" className={status?.liepin_opened ? "border-emerald-500/40 text-emerald-600 dark:text-emerald-400" : "text-muted-foreground"}>
                    猎聘 {status?.liepin_opened ? "✓ 已打开" : "待打开"}
                  </Badge>
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                提示：请确保在打开的 Chrome 中已完成账号登录，保持该 Chrome 窗口开启，直接在职位匹配页输入求职方向即可实时检索！
              </p>
              <div className="flex items-center gap-2 pt-1">
                <Button size="sm" variant="outline" className="h-7 gap-1.5 text-xs" asChild>
                  <a href="https://www.zhipin.com" target="_blank" rel="noreferrer">
                    打开 Boss直聘 <ExternalLink className="h-3 w-3" />
                  </a>
                </Button>
                <Button size="sm" variant="outline" className="h-7 gap-1.5 text-xs" asChild>
                  <a href="https://www.liepin.com" target="_blank" rel="noreferrer">
                    打开 猎聘网 <ExternalLink className="h-3 w-3" />
                  </a>
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-3.5">
              <div className="flex items-center justify-between gap-2 rounded-lg border border-border bg-muted/40 p-3">
                <div className="flex flex-col gap-0.5">
                  <span className="text-xs font-medium text-foreground">方式一：一键自动唤起 Chrome</span>
                  <span className="text-[11px] text-muted-foreground">调用后台进程调起独立数据目录的调试浏览器</span>
                </div>
                <Button size="sm" variant="default" className="h-8 gap-1.5 px-3 text-xs" onClick={handleLaunch} disabled={launching}>
                  {launching ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5 fill-current" />}
                  {launching ? "正在唤起…" : "一键启动 Chrome"}
                </Button>
              </div>

              <div className="flex flex-col gap-2 rounded-lg border border-border bg-muted/40 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-foreground">方式二：终端执行启动命令</span>
                  <Button size="sm" variant="outline" className="h-6 gap-1 px-2 text-[11px]" onClick={handleCopy}>
                    {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
                    {copied ? "已复制" : "复制命令"}
                  </Button>
                </div>
                <div className="flex items-center gap-2 rounded border border-border/60 bg-background px-2.5 py-1.5 font-mono text-[11px] text-muted-foreground">
                  <Terminal className="h-3.5 w-3.5 shrink-0 text-primary/70" />
                  <span className="truncate">{status?.command || "powershell -ExecutionPolicy Bypass -File scripts/start_chrome_cdp.ps1"}</span>
                </div>
              </div>

              <div className="rounded-lg border border-dashed border-border/80 p-3 text-[11px] leading-relaxed text-muted-foreground">
                <span className="font-semibold text-foreground">方式三（推荐双击）：</span>
                在项目根目录下直接双击运行 <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-foreground">{status?.bat_path || "scripts\\start_chrome_cdp.bat"}</code>，窗口启动后分别登录 Boss 直聘与猎聘即可。
              </div>
            </div>
          )}
        </div>

        {/* 底部操作 */}
        <div className="mt-2 flex items-center justify-end gap-2 border-t border-border/60 pt-3">
          <Button size="sm" variant="outline" className="h-8 px-4 text-xs" onClick={onClose}>
            {isConnected ? "完成并开始匹配" : "关闭"}
          </Button>
        </div>
      </div>
    </div>
  )
}
