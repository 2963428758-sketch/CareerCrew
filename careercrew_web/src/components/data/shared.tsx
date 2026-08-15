import { Brain } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"

/** 数据面板共用小件：错误卡片 / 空态卡片。 */

export function ErrorCard({ msg }: { msg: string }) {
  return <Card className="border-destructive/40"><CardContent className="p-4 text-[13px] text-destructive">加载失败：{msg}</CardContent></Card>
}

export function EmptyCard({ text }: { text: string }) {
  return (
    <Card>
      <CardContent className="flex items-center justify-center p-12 text-ink-faint">
        <Brain className="mr-2 h-4 w-4" />{text}
      </CardContent>
    </Card>
  )
}
