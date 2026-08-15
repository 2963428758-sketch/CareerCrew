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
    <main className="flex min-h-screen items-center justify-center bg-background px-5">
      <section className="w-full max-w-md rounded-xl border bg-card p-8 shadow-sm">
        <div className="mb-7 flex items-center gap-3">
          <Mark />
          <div>
            <h1 className="font-display text-xl font-bold">CareerCrew</h1>
            <p className="mt-0.5 text-sm text-muted-foreground">{isBootstrap ? "创建首个管理员账号" : "登录以继续使用"}</p>
          </div>
        </div>
        <form className="space-y-4" onSubmit={submit}>
          <label className="block text-sm font-medium">用户名
            <input required minLength={3} maxLength={64} pattern="[A-Za-z0-9_.-]+" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} className="mt-1.5 w-full rounded-md border bg-background px-3 py-2.5 outline-none focus:ring-2 focus:ring-ring" />
          </label>
          <label className="block text-sm font-medium">密码
            <input required minLength={12} maxLength={256} type="password" autoComplete={isBootstrap ? "new-password" : "current-password"} value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1.5 w-full rounded-md border bg-background px-3 py-2.5 outline-none focus:ring-2 focus:ring-ring" />
          </label>
          {isBootstrap && <p className="text-xs leading-5 text-muted-foreground">首次初始化仅在开发环境且尚无账号时可用。密码至少 12 位。</p>}
          {error && <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
          <button disabled={submitting} className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground disabled:opacity-60">
            {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
            {isBootstrap ? "创建管理员并登录" : "登录"}
          </button>
        </form>
      </section>
    </main>
  )
}

export function AuthLoading() {
  return <main className="flex min-h-screen items-center justify-center bg-background text-muted-foreground"><Loader2 className="mr-2 h-5 w-5 animate-spin" />正在恢复会话…</main>
}

function Mark() {
  return <svg width="30" height="30" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <circle cx="12" cy="5" r="2.5" fill="#0D9488" /><circle cx="5" cy="17" r="2.5" fill="#D97706" /><circle cx="19" cy="17" r="2.5" fill="#7C3AED" />
    <path d="M12 7.5L5.5 14.5M12 7.5L18.5 14.5M7 17h10" stroke="#2D3340" strokeWidth="1.2" strokeLinecap="round" />
  </svg>
}
