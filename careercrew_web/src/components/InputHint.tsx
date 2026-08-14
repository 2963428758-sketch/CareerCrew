import { CornerDownLeft } from "lucide-react"

interface InputHintProps {
  /** 页面特色提示，追加在快捷键说明之后；不传则只显示快捷键 */
  tip?: string
}

/**
 * 输入框下方的统一快捷键提示：发送 · Shift + Enter 换行 [· tip]
 * 所有聊天页面共用，避免各页文案漂移。
 */
export function InputHint({ tip }: InputHintProps) {
  return (
    <p className="mx-auto mt-2 flex max-w-3xl items-center gap-1 text-[11px] text-muted-foreground">
      <CornerDownLeft className="h-3 w-3" /> 发送
      <span className="mx-1">·</span>
      Shift + Enter 换行
      {tip && (
        <>
          <span className="mx-1">·</span>
          {tip}
        </>
      )}
    </p>
  )
}
