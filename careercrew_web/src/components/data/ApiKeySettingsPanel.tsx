import { useEffect, useState } from "react"
import { AlertCircle, CheckCircle2, Eye, EyeOff, KeyRound, Loader2, Sparkles, Trash2, ExternalLink } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { apiFetch } from "@/lib/auth"
import { apiErrorText, networkErrorText } from "@/lib/errors"

interface ApiKeyStatus {
  has_key: boolean
  masked_key: string
  provider: string
  system_configured: boolean
}

export function ApiKeySettingsPanel() {
  const [status, setStatus] = useState<ApiKeyStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const [inputKey, setInputKey] = useState("")
  const [showKey, setShowKey] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [actionError, setActionError] = useState("")

  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)

  const [clearing, setClearing] = useState(false)

  const loadStatus = async () => {
    setLoading(true)
    setError("")
    try {
      const res = await apiFetch("/api/settings/apikey")
      if (!res.ok) throw new Error(await apiErrorText(res, "获取 API Key 配置失败"))
      const data: ApiKeyStatus = await res.json()
      setStatus(data)
    } catch (e) {
      setError(networkErrorText(e, "加载配置失败，请检查网络连接"))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadStatus()
  }, [])

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    const key = inputKey.trim()
    if (!key) {
      setActionError("请输入有效的 API Key")
      return
    }
    setSaving(true)
    setActionError("")
    setSaveSuccess(false)
    try {
      const res = await apiFetch("/api/settings/apikey", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: key }),
      })
      if (!res.ok) throw new Error(await apiErrorText(res, "保存 API Key 失败"))
      setInputKey("")
      setSaveSuccess(true)
      await loadStatus()
      setTimeout(() => setSaveSuccess(false), 4000)
    } catch (e) {
      setActionError(networkErrorText(e, "保存失败，请稍后重试"))
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    const key = inputKey.trim()
    if (!key) {
      setActionError("请先在输入框中输入待测试的 API Key")
      return
    }
    setTesting(true)
    setTestResult(null)
    setActionError("")
    try {
      const res = await apiFetch("/api/settings/apikey/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: key, provider: "dashscope" }),
      })
      if (!res.ok) throw new Error(await apiErrorText(res, "连通性测试请求失败"))
      const data = await res.json()
      setTestResult(data)
    } catch (e) {
      setTestResult({ ok: false, message: networkErrorText(e, "测试请求失败，请检查服务网络") })
    } finally {
      setTesting(false)
    }
  }

  const handleClear = async () => {
    if (!window.confirm("确定要移除个人专属 API Key 吗？移除后将自动恢复使用系统默认服务。")) {
      return
    }
    setClearing(true)
    setActionError("")
    try {
      const res = await apiFetch("/api/settings/apikey", { method: "DELETE" })
      if (!res.ok) throw new Error(await apiErrorText(res, "清除 API Key 失败"))
      await loadStatus()
    } catch (e) {
      setActionError(networkErrorText(e, "清除失败，请稍后重试"))
    } finally {
      setClearing(false)
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-32 w-full rounded-lg" />
        <Skeleton className="h-48 w-full rounded-lg" />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-[13px] text-red-600 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* 当前生效状态卡片 */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-[14px] font-medium flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-brand-primary" />
              当前生效的大模型凭证
            </CardTitle>
            <span className="inline-flex items-center rounded-full bg-brand-primary/10 px-2.5 py-0.5 text-xs font-medium text-brand-primary">
              阿里云百炼 (DashScope)
            </span>
          </div>
          <CardDescription className="text-xs text-ink-faint">
            系统所有 Agent、模拟面试与求职会诊均基于此凭证调度通义千问大模型。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-lg border border-border/60 bg-workspace/50 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-medium text-ink">运行模式：</span>
                  {status?.has_key ? (
                    <span className="inline-flex items-center gap-1 text-[12px] font-medium text-emerald-600 dark:text-emerald-400">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      个人专属密钥 (BYOK)
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[12px] font-medium text-blue-600 dark:text-blue-400">
                      <Sparkles className="h-3.5 w-3.5" />
                      系统统一托管密钥
                    </span>
                  )}
                </div>
                <p className="text-[12px] text-ink-faint">
                  {status?.has_key
                    ? `当前账号已绑定个人 DashScope 密钥：${status.masked_key}`
                    : status?.system_configured
                    ? "当前使用系统环境变量全局配置的 DashScope 默认服务。"
                    : "系统默认密钥未配置，请在下方填入您的专属 API Key 以开始使用。"}
                </p>
              </div>

              {status?.has_key && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleClear}
                  disabled={clearing}
                  className="h-8 text-xs text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/30 hover:text-rose-700 border-rose-200 dark:border-rose-900"
                >
                  {clearing ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="h-3.5 w-3.5 mr-1" />
                  )}
                  移除个人密钥
                </Button>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 配置新密钥卡片 */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-[14px] font-medium">
            {status?.has_key ? "更新个人 API Key" : "配置个人 DashScope API Key"}
          </CardTitle>
          <CardDescription className="text-xs text-ink-faint">
            输入您的阿里云百炼 DashScope API 密钥。密钥仅供当前账号执行大模型推理，存储于安全加密的私有存储中。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSave} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-[13px] font-medium text-ink" htmlFor="apikey-input">
                DashScope API Key (sk-...)
              </label>
              <div className="relative">
                <Input
                  id="apikey-input"
                  type={showKey ? "text" : "password"}
                  value={inputKey}
                  onChange={(e) => setInputKey(e.target.value)}
                  placeholder="sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                  className="pr-10 font-mono text-[13px] bg-workspace"
                  autoComplete="off"
                />
                <button
                  type="button"
                  onClick={() => setShowKey(!showKey)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-faint hover:text-ink transition-colors p-1"
                  title={showKey ? "隐藏密钥" : "显示密钥"}
                >
                  {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {actionError && (
              <div className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 p-2.5 text-[12px] text-red-600 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-400">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                <span>{actionError}</span>
              </div>
            )}

            {saveSuccess && (
              <div className="flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 p-2.5 text-[12px] text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/30 dark:text-emerald-400">
                <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                <span>API Key 已成功保存并立即生效！</span>
              </div>
            )}

            {testResult && (
              <div
                className={`flex items-center gap-2 rounded-md border p-2.5 text-[12px] ${
                  testResult.ok
                    ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/30 dark:text-emerald-400"
                    : "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-400"
                }`}
              >
                {testResult.ok ? (
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
                ) : (
                  <AlertCircle className="h-3.5 w-3.5 shrink-0 text-amber-600" />
                )}
                <span>{testResult.message}</span>
              </div>
            )}

            <div className="flex items-center gap-3 pt-1">
              <Button
                type="submit"
                disabled={saving || !inputKey.trim()}
                className="h-8 text-xs font-medium"
              >
                {saving && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />}
                保存并生效
              </Button>

              <Button
                type="button"
                variant="outline"
                onClick={handleTest}
                disabled={testing || !inputKey.trim()}
                className="h-8 text-xs"
              >
                {testing ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                    正在测试连接...
                  </>
                ) : (
                  "测试连通性"
                )}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* 获取密钥指南卡片 */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-[13px] font-medium">如何获取阿里云百炼 API Key？</CardTitle>
        </CardHeader>
        <CardContent className="text-xs text-ink-faint space-y-2.5">
          <ol className="list-decimal pl-4 space-y-1.5 text-ink leading-relaxed">
            <li>
              访问{" "}
              <a
                href="https://bailian.console.aliyun.com/"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-0.5 text-brand-primary underline underline-offset-2 hover:opacity-80"
              >
                阿里云百炼大模型平台控制台
                <ExternalLink className="h-3 w-3" />
              </a>
              ，完成实名认证。
            </li>
            <li>在右上角头像菜单或左侧导航点击「API-KEY 管理」。</li>
            <li>点击「创建新的 API-KEY」，复制生成的以 <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">sk-</code> 开头的密钥串。</li>
            <li>将复制的密钥填入上方输入框，可先点击「测试连通性」验证，确认无误后点击「保存并生效」。</li>
          </ol>
          <p className="text-[11px] text-ink-faint pt-1 border-t border-border/40">
            * 提示：阿里云百炼新用户通常享有免费 Token 调用额度，可充分用于体验 CareerCrew 职业导师的全部功能。
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
