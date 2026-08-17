import { useCallback, useEffect, useRef, useState } from "react"

/** 轻量 toast：showToast 后 2s 自动消失（页面级反馈提示）。 */
export function useToast() {
  const [toast, setToast] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const showToast = useCallback((text: string) => {
    setToast(text)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setToast(null), 2000)
  }, [])

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  return { toast, showToast }
}
