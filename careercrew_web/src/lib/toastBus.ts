/** 全局错误提示总线：任何静默失败点都可以 notifyError() 弹出一条全局 toast。 */

export interface ToastNotice {
  id: number
  kind: "error" | "info"
  text: string
}

type Listener = (notice: ToastNotice) => void

let seq = 0
const listeners = new Set<Listener>()

export function subscribeToasts(listener: Listener): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function notifyToast(kind: "error" | "info", text: string): void {
  const notice: ToastNotice = { id: ++seq, kind, text }
  for (const listener of listeners) listener(notice)
}

/** 全局错误提示（底部居中，自动消失）。 */
export function notifyError(text: string): void {
  notifyToast("error", text)
}

/** 全局信息提示。 */
export function notifyInfo(text: string): void {
  notifyToast("info", text)
}
