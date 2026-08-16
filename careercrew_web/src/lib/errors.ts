/** 统一把 API / 网络错误转成用户可读的中文提示。 */

const STATUS_TEXT: Record<number, string> = {
  400: "请求有误，请检查输入后重试",
  401: "登录状态已失效，请重新登录",
  403: "没有权限执行该操作",
  404: "请求的内容不存在或已被删除",
  409: "操作冲突，请刷新后重试",
  413: "文件过大，超出了大小限制",
  422: "请求参数不正确，请检查后重试",
  429: "操作过于频繁，请稍后再试",
  500: "服务器内部错误，请稍后重试",
  502: "服务暂时不可用，请稍后重试",
  503: "服务暂时不可用，请稍后重试",
  504: "服务响应超时，请稍后重试",
}

const hasCjk = (s: string) => /[\u4e00-\u9fff]/.test(s)

/** 校验错误字段位置（去掉 body/query/path 等无意义前缀）。 */
const fieldOf = (err: { loc?: unknown[] }) =>
  (err.loc ?? [])
    .filter((p) => !["body", "query", "path", "header", "cookie"].includes(String(p)))
    .join(".") || "参数"

/**
 * 从 HTTP 响应提取后端 detail 并转成中文提示：
 * - detail 为字符串且已是中文 → 原样返回（后端已统一中文化）
 * - detail 为字符串但非中文 → 回退到状态码文案
 * - detail 为 FastAPI 校验错误数组 → 汇总第一条中文可读信息
 * - 其余 → 状态码文案或 fallback
 */
export async function apiErrorText(
  resp: Response,
  fallback = "请求失败，请稍后重试"
): Promise<string> {
  let body: { detail?: unknown } | null = null
  try {
    body = (await resp.json()) as { detail?: unknown }
  } catch {
    body = null
  }
  const detail = body?.detail
  if (typeof detail === "string" && detail.trim()) {
    return hasCjk(detail) ? detail : STATUS_TEXT[resp.status] ?? fallback
  }
  if (Array.isArray(detail) && detail.length > 0) {
    const parts = detail
      .slice(0, 3)
      .map((e) => {
        const msg = String((e as { msg?: unknown }).msg ?? "")
        if (hasCjk(msg)) return msg
        return `「${fieldOf(e as { loc?: unknown[] })}」填写不正确`
      })
      .filter(Boolean)
    if (parts.length > 0) return parts.join("；")
  }
  return STATUS_TEXT[resp.status] ?? fallback
}

/**
 * 把 fetch 抛出的异常转成中文提示：
 * 网络层错误（Failed to fetch 等）→ 统一网络文案；
 * 业务层 Error（已用 apiErrorText 构造）→ 原样返回 message。
 */
export function networkErrorText(
  err: unknown,
  fallback = "网络连接失败，请检查网络后重试"
): string {
  if (!(err instanceof Error)) return fallback
  const msg = err.message || ""
  const lowered = msg.toLowerCase()
  if (
    msg === "Failed to fetch" ||
    msg === "Load failed" ||
    msg === "Network request failed" ||
    lowered.includes("networkerror") ||
    lowered.includes("failed to fetch") ||
    lowered.includes("load failed")
  ) {
    return fallback
  }
  return msg
}
