import { useCallback, useRef, useState } from "react"

/**
 * 语音作答（三期最小交付）：基于浏览器 Web Speech API 的听写。
 * - 不支持的环境返回 supported=false，UI 隐藏按钮，不影响原有键盘输入；
 * - 转写结果追加到回调，由用户在发送前校正（转写校正 = 直接编辑文本）。
 */
type SpeechRecognitionLike = {
  lang: string
  continuous: boolean
  interimResults: boolean
  start: () => void
  stop: () => void
  onresult: ((event: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null
  onend: (() => void) | null
  onerror: ((event: { error?: string }) => void) | null
}

type SpeechCtor = new () => SpeechRecognitionLike

// 构造器在模块加载时解析一次。绝不能用 useState 存函数值——React 会把它
// 当作惰性初始化器/updater 调用（basicStateReducer），等于无 new 调用 DOM
// 构造器，直接抛 "Please use the 'new' operator" 并卸载整棵组件树。
const w = window as unknown as Record<string, unknown>
const SPEECH_CTOR = ((w.SpeechRecognition ?? w.webkitSpeechRecognition) ?? null) as SpeechCtor | null

export function useSpeechRecognition(onFinalText: (text: string) => void): {
  supported: boolean
  listening: boolean
  error: string
  toggle: () => void
} {
  const [listening, setListening] = useState(false)
  const [error, setError] = useState("")
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const callbackRef = useRef(onFinalText)
  callbackRef.current = onFinalText

  const toggle = useCallback(() => {
    if (!SPEECH_CTOR) return
    if (listening) {
      recognitionRef.current?.stop()
      setListening(false)
      return
    }
    const recognition = new SPEECH_CTOR()
    recognition.lang = "zh-CN"
    recognition.continuous = true
    recognition.interimResults = false
    recognition.onresult = (event) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i]
        if (result?.isFinal) {
          const text = result[0]?.transcript?.trim()
          if (text) callbackRef.current(text)
        }
      }
    }
    recognition.onerror = (event) => {
      setError(event?.error === "not-allowed" ? "麦克风权限被拒绝" : "语音识别出错，请重试")
      setListening(false)
    }
    recognition.onend = () => setListening(false)
    recognitionRef.current = recognition
    setError("")
    try {
      recognition.start()
      setListening(true)
    } catch {
      setError("语音识别启动失败，请重试")
    }
  }, [listening])

  return { supported: Boolean(SPEECH_CTOR), listening, error, toggle }
}
