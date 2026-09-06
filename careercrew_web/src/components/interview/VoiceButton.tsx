import { Mic, MicOff } from "lucide-react"

import { Tooltip } from "@/components/ui/tooltip"
import { useSpeechRecognition } from "@/hooks/useSpeechRecognition"

/** 语音作答按钮：浏览器支持 Web Speech API 时显示；转写结果由用户校正后发送。 */
export function VoiceButton({ onText, onError }: {
  onText: (text: string) => void
  onError: (message: string) => void
}) {
  const { supported, listening, error, toggle } = useSpeechRecognition(onText)

  if (!supported) return null
  return (
    <Tooltip label={listening ? "停止语音输入" : "语音作答"}>
      <button
        type="button"
        aria-label={listening ? "停止语音输入" : "开始语音输入"}
        onClick={() => {
          toggle()
          if (error) onError(error)
        }}
        className={
          "flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-[9px] border transition-colors " +
          (listening
            ? "border-destructive/50 bg-destructive/10 text-destructive"
            : "border-[var(--border-soft)] bg-workspace text-ink-faint hover:bg-surface-2 hover:text-ink")
        }
      >
        {listening ? <MicOff className="h-4 w-4" strokeWidth={1.7} /> : <Mic className="h-4 w-4" strokeWidth={1.7} />}
      </button>
    </Tooltip>
  )
}
