import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

/**
 * lib/auth.ts 认证地基测试：内存 token 注入、401 刷新重试（最多一次）、
 * 并发 401 单飞刷新、刷新失败清会话、restoreSession 去重。
 *
 * 模块持有私有会话状态，每个用例通过 vi.resetModules + 动态 import 取干净实例。
 */

const jsonResp = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })

/** Response 的 body 只能读一次：用工厂保证每个用例/每次入队拿到新实例。 */
const tokenResp = (t: string) =>
  jsonResp({ access_token: t, user: { id: "u1", username: "alice", role: "user" } })
const TOKEN_1 = () => tokenResp("tok-1")
const TOKEN_2 = () => tokenResp("tok-2")

/** fetch mock：按调用顺序出队响应；记录每次请求的 Authorization 头。 */
function mockFetchQueue(resps: Array<Response | Error>) {
  const authHeaders: Array<string | null> = []
  const paths: string[] = []
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    paths.push(String(input))
    authHeaders.push(new Headers(init?.headers).get("Authorization"))
    const next = resps.shift()
    if (next instanceof Error) throw next
    return next ?? jsonResp({}, 500)
  })
  vi.stubGlobal("fetch", fn)
  return { fn, authHeaders, paths }
}

async function freshAuth() {
  vi.resetModules()
  return await import("@/lib/auth")
}

beforeEach(() => {
  vi.unstubAllGlobals()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("apiFetch 401 刷新重试", () => {
  it("登录后请求携带 Bearer token", async () => {
    const auth = await freshAuth()
    const { authHeaders } = mockFetchQueue([TOKEN_1(), jsonResp({ ok: true })])
    await auth.login("alice", "pw")
    await auth.apiFetch("/api/data/profile")
    expect(authHeaders[0]).toBeNull() // login 本体不带头
    expect(authHeaders[1]).toBe("Bearer tok-1")
  })

  it("401 -> 刷新成功 -> 用新 token 重试一次并返回新结果", async () => {
    const auth = await freshAuth()
    const { authHeaders, paths } = mockFetchQueue([
      TOKEN_1(),
      jsonResp({}, 401), // 业务请求首次
      TOKEN_2(), // /api/auth/refresh
      jsonResp({ data: "fresh" }), // 重试
    ])
    await auth.login("alice", "pw")
    const resp = await auth.apiFetch("/api/data/profile")
    expect(resp.status).toBe(200)
    // 调用序：login -> 业务 401 -> refresh -> 携新 token 重试
    expect(paths[1]).toBe("/api/data/profile")
    expect(paths[2]).toBe("/api/auth/refresh")
    expect(paths[3]).toBe("/api/data/profile")
    expect(authHeaders[3]).toBe("Bearer tok-2")
  })

  it("刷新失败：返回原始 401 且会话被清除", async () => {
    const auth = await freshAuth()
    mockFetchQueue([
      TOKEN_1(),
      jsonResp({}, 401),
      jsonResp({}, 401), // refresh 失败
    ])
    await auth.login("alice", "pw")
    const resp = await auth.apiFetch("/api/data/profile")
    expect(resp.status).toBe(401)
    expect(auth.getAuthSnapshot().status).toBe("anonymous")
  })

  it("重试仍 401：清会话（刷新令牌已失效/轮换断链）", async () => {
    const auth = await freshAuth()
    mockFetchQueue([
      TOKEN_1(),
      jsonResp({}, 401),
      TOKEN_2(),
      jsonResp({}, 401),
    ])
    await auth.login("alice", "pw")
    const resp = await auth.apiFetch("/api/data/profile")
    expect(resp.status).toBe(401)
    expect(auth.getAuthSnapshot().status).toBe("anonymous")
  })

  it("并发多个 401 只触发一次刷新（single-flight）", async () => {
    const auth = await freshAuth()
    const { fn } = mockFetchQueue([
      TOKEN_1(),
      jsonResp({}, 401),
      jsonResp({}, 401),
      TOKEN_2(), // 仅一次 refresh
      jsonResp({ n: 1 }),
      jsonResp({ n: 2 }),
    ])
    await auth.login("alice", "pw")
    const [a, b] = await Promise.all([
      auth.apiFetch("/api/x"),
      auth.apiFetch("/api/y"),
    ])
    expect(a.status).toBe(200)
    expect(b.status).toBe(200)
    const refreshCalls = fn.mock.calls.filter(([i]) => String(i) === "/api/auth/refresh")
    expect(refreshCalls.length).toBe(1)
  })

  it("非 401 响应直接透传，不触发刷新", async () => {
    const auth = await freshAuth()
    const { fn } = mockFetchQueue([
      TOKEN_1(),
      jsonResp({ forbidden: true }, 403),
    ])
    await auth.login("alice", "pw")
    const resp = await auth.apiFetch("/api/x")
    expect(resp.status).toBe(403)
    expect(fn.mock.calls.length).toBe(2) // login + 业务请求，无 refresh
  })
})

describe("restoreSession / logout", () => {
  it("并发 restoreSession 复用同一次刷新调用", async () => {
    const auth = await freshAuth()
    const { fn } = mockFetchQueue([TOKEN_1(), TOKEN_2()])
    const [a, b] = await Promise.all([auth.restoreSession(), auth.restoreSession()])
    expect(a).toBe(true)
    expect(b).toBe(true)
    const refreshCalls = fn.mock.calls.filter(([i]) => String(i) === "/api/auth/refresh")
    expect(refreshCalls.length).toBe(1)
  })

  it("logout 网络失败也保证本地会话清除", async () => {
    const auth = await freshAuth()
    mockFetchQueue([TOKEN_1(), new Error("network down")])
    await auth.login("alice", "pw")
    await expect(auth.logout()).rejects.toThrow()
    expect(auth.getAuthSnapshot().status).toBe("anonymous")
  })
})
