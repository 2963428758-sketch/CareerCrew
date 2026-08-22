/** 全局提示总线：任何静默失败点都可以 notify*() 弹出一条全局 toast。 */

export interface ToastNotice {
  id: number
  kind: "success" | "error" | "info"
  text: string
}

type Listener = (notice: ToastNotice) => void

let seq = 0
const listeners = new Set<Listener>()

/** 同文案去重窗口（ms）：StrictMode 双挂载/多组件同时报同一错误时只弹一条。 */
const DEDUPE_WINDOW_MS = 1500
let lastKind: ToastNotice["kind"] | null = null
let lastText = ""
let lastAt = 0

export function subscribeToasts(listener: Listener): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function notifyToast(kind: "success" | "error" | "info", text: string): void {
  const now = Date.now()
  if (kind === lastKind && text === lastText && now - lastAt < DEDUPE_WINDOW_MS) {
    return
  }
  lastKind = kind
  lastText = text
  lastAt = now
  const notice: ToastNotice = { id: ++seq, kind, text }
  for (const listener of listeners) listener(notice)
}

/** 成功提示（顶部居中，自动消失）。 */
export function notifySuccess(text: string): void {
  notifyToast("success", text)
}

/** 全局错误提示。 */
export function notifyError(text: string): void {
  notifyToast("error", text)
}

/** 全局信息提示。 */
export function notifyInfo(text: string): void {
  notifyToast("info", text)
}
