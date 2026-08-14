export interface AuthUser {
  id: string
  username: string
  role: "admin" | "user"
}

interface TokenResponse {
  access_token: string
  user: AuthUser
}

export interface AuthSnapshot {
  status: "loading" | "authenticated" | "anonymous"
  user: AuthUser | null
}

let accessToken: string | null = null
let snapshot: AuthSnapshot = { status: "loading", user: null }
let refreshInFlight: Promise<boolean> | null = null
let restoreInFlight: Promise<boolean> | null = null
const subscribers = new Set<() => void>()

const notify = () => subscribers.forEach((listener) => listener())

const setSession = (payload: TokenResponse) => {
  accessToken = payload.access_token
  snapshot = { status: "authenticated", user: payload.user }
  notify()
}

const clearSession = () => {
  accessToken = null
  if (snapshot.status !== "anonymous" || snapshot.user !== null) {
    snapshot = { status: "anonymous", user: null }
    notify()
  }
}

const rawFetch = (input: RequestInfo | URL, init?: RequestInit) =>
  fetch(input, { ...init, credentials: "include" })

async function refreshAccessToken(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = rawFetch("/api/auth/refresh", { method: "POST" })
      .then(async (response) => {
        if (!response.ok) return false
        setSession(await response.json() as TokenResponse)
        return true
      })
      .catch(() => false)
      .finally(() => { refreshInFlight = null })
  }
  const refreshed = await refreshInFlight
  if (!refreshed) clearSession()
  return refreshed
}

/** 所有业务 API 的唯一入口：携带内存 access token，401 时最多刷新并重试一次。 */
export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`)
  const request = () => rawFetch(input, { ...init, headers })

  let response = await request()
  if (response.status !== 401) return response
  if (!await refreshAccessToken()) return response

  const retryHeaders = new Headers(init.headers)
  if (accessToken) retryHeaders.set("Authorization", `Bearer ${accessToken}`)
  response = await rawFetch(input, { ...init, headers: retryHeaders })
  if (response.status === 401) clearSession()
  return response
}

export const getAuthSnapshot = () => snapshot

export const subscribeAuth = (listener: () => void) => {
  subscribers.add(listener)
  return () => subscribers.delete(listener)
}

/** 启动时只使用 HttpOnly Cookie 换取新的内存令牌，永不读写 Web Storage。 */
export function restoreSession(): Promise<boolean> {
  if (!restoreInFlight) {
    restoreInFlight = refreshAccessToken().finally(() => { restoreInFlight = null })
  }
  return restoreInFlight
}

export async function login(username: string, password: string): Promise<void> {
  const response = await rawFetch("/api/auth/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  })
  if (!response.ok) throw new Error(await responseMessage(response, "用户名或密码不正确"))
  setSession(await response.json() as TokenResponse)
}

export async function bootstrapAdmin(username: string, password: string): Promise<void> {
  const response = await rawFetch("/api/auth/bootstrap", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  })
  if (!response.ok) throw new Error(await responseMessage(response, "无法初始化管理员"))
  await login(username, password)
}

export async function getBootstrapAvailability(): Promise<boolean> {
  const response = await rawFetch("/api/auth/bootstrap")
  if (!response.ok) return false
  const body = await response.json() as { available?: unknown }
  return body.available === true
}

export async function logout(): Promise<void> {
  try {
    await rawFetch("/api/auth/logout", { method: "POST" })
  } finally {
    clearSession()
  }
}

async function responseMessage(response: Response, fallback: string): Promise<string> {
  const body = await response.json().catch(() => null) as { detail?: unknown } | null
  return typeof body?.detail === "string" ? body.detail : fallback
}
