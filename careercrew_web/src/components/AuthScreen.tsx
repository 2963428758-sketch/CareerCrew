import { useEffect, useState, type FormEvent } from "react"
import { Loader2 } from "lucide-react"
import { bootstrapAdmin, getBootstrapAvailability, login } from "@/lib/auth"

export function AuthScreen() {
  const [bootstrapAvailable, setBootstrapAvailable] = useState(false)
  const [checking, setChecking] = useState(true)
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    let active = true
    getBootstrapAvailability()
      .then((available) => active && setBootstrapAvailable(available))
      .finally(() => active && setChecking(false))
    return () => { active = false }
  }, [])

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError("")
    setSubmitting(true)
    try {
      if (bootstrapAvailable) await bootstrapAdmin(username, password)
      else await login(username, password)
    } catch (err) {
      setError((err as Error).message)
      if (bootstrapAvailable) setBootstrapAvailable(await getBootstrapAvailability())
    } finally {
      setSubmitting(false)
    }
  }

  if (checking) return <AuthLoading />

  const isBootstrap = bootstrapAvailable
  return (
    <main className="flex min-h-screen items-center justify-center bg-shell px-5">
      <section className="w-full max-w-md rounded-[14px] border border-[var(--border-soft)] bg-workspace p-8 shadow-workspace">
        <div className="mb-7 flex items-center gap-3">
          <Mark />
          <div>
            <h1 className="text-[16px] font-medium tracking-[-0.01em] text-ink">CareerCrew</h1>
            <p className="mt-0.5 text-[13px] text-ink-soft">{isBootstrap ? "创建首个管理员账号" : "登录以继续使用"}</p>
          </div>
        </div>
        <form className="space-y-4" onSubmit={submit}>
          <label className="block text-[13px] font-medium text-ink">用户名
            <input required minLength={3} maxLength={64} pattern="[A-Za-z0-9_.\-]+" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} className="mt-1.5 w-full rounded-[7px] border border-input bg-workspace px-3 py-2 text-[14px] outline-none transition-colors duration-100 placeholder:text-ink-faint focus-visible:ring-2 focus-visible:ring-ring/40" />
          </label>
          <label className="block text-[13px] font-medium text-ink">密码
            <input required minLength={isBootstrap ? 12 : 1} maxLength={256} type="password" autoComplete={isBootstrap ? "new-password" : "current-password"} value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1.5 w-full rounded-[7px] border border-input bg-workspace px-3 py-2 text-[14px] outline-none transition-colors duration-100 placeholder:text-ink-faint focus-visible:ring-2 focus-visible:ring-ring/40" />
          </label>
          {isBootstrap && <p className="text-[12px] leading-5 text-ink-soft">首次初始化仅在开发环境且尚无账号时可用。密码至少 12 位。</p>}
          {error && <p role="alert" className="rounded-[7px] border border-destructive/40 bg-destructive/10 px-3 py-2 text-[13px] text-destructive">{error}</p>}
          <button disabled={submitting} className="flex h-[34px] w-full items-center justify-center gap-2 rounded-[7px] bg-button-ink px-4 text-[13px] font-medium text-button-onink transition-opacity duration-100 hover:opacity-90 disabled:opacity-60">
            {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
            {isBootstrap ? "创建管理员并登录" : "登录"}
          </button>
        </form>
      </section>
    </main>
  )
}

export function AuthLoading() {
  return <main className="flex min-h-screen items-center justify-center bg-shell text-ink-soft"><Loader2 className="mr-2 h-5 w-5 animate-spin" />正在恢复会话…</main>
}

function Mark() {
  return <svg width="30" height="30" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <circle cx="12" cy="5" r="2.5" fill="#0D9488" /><circle cx="5" cy="17" r="2.5" fill="#D97706" /><circle cx="19" cy="17" r="2.5" fill="#7C3AED" />
    <path d="M12 7.5L5.5 14.5M12 7.5L18.5 14.5M7 17h10" stroke="#2D3340" strokeWidth="1.2" strokeLinecap="round" />
  </svg>
}
