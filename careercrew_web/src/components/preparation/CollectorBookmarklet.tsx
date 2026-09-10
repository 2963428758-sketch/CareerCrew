import { useMemo, useState } from "react"
import { Copy } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useToast } from "@/hooks/useToast"
/**
 * 通用岗位采集器书签脚本：在任意招聘网站页面执行——
 * 取当前 URL、页面标题与选中的 JD 文本，跳回 CareerCrew 岗位准备页预填录入表单。
 * 纯前端跳转，不跨域请求，天然规避 CORS 与站点风控。
 */
export function CollectorBookmarklet() {
  const { showToast } = useToast()
  const code = useMemo(() => {
    const origin = window.location.origin
    return (
      "javascript:(function(){var s=window.getSelection?String(window.getSelection()):'';" +
      "location.href='" + origin + "/preparation?collect=1" +
      "&url='+encodeURIComponent(location.href)" +
      "&title='+encodeURIComponent(document.title)" +
      "&jd='+encodeURIComponent(s);})();"
    )
  }, [])
  const [copied, setCopied] = useState(false)

  return (
    <div className="mt-1.5">
      <code className="block max-h-[72px] overflow-y-auto break-all rounded-[6px] bg-surface-1 p-1.5 font-mono text-[10.5px] leading-relaxed text-ink-soft">
        {code}
      </code>
      <Button
        variant="outline"
        size="sm"
        className="mt-1 h-[22px] text-[11px]"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(code)
            setCopied(true)
            showToast("已复制，请新建书签并粘贴到网址栏")
          } catch {
            showToast("复制失败，请手动选择代码复制")
          }
        }}
      >
        <Copy className="h-3 w-3" /> {copied ? "已复制" : "复制书签代码"}
      </Button>
    </div>
  )
}
