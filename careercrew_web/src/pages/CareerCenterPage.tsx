import { useEffect, useState } from "react"
import { ClipboardList, Compass, Download, FileSpreadsheet, ListTodo, MessagesSquare, Mic, RefreshCw, TrendingUp, Users } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ToastBubble } from "@/components/conversation/ToastBubble"
import { useToast } from "@/hooks/useToast"
import { listBoard, type BoardRow } from "@/lib/career"
import { cn } from "@/lib/utils"
import { BoardTab } from "@/components/career/BoardTab"
import { TasksTab } from "@/components/career/TasksTab"
import { MaterialsTab } from "@/components/career/MaterialsTab"
import { FollowupsTab } from "@/components/career/FollowupsTab"
import { OffersTab } from "@/components/career/OffersTab"
import { ReviewsTab } from "@/components/career/ReviewsTab"
import { ContactsTab } from "@/components/career/ContactsTab"
import { StatsTab } from "@/components/career/StatsTab"
import { PrivacyTab } from "@/components/career/PrivacyTab"

const TABS = [
  { id: "board", label: "进度看板", icon: Compass },
  { id: "tasks", label: "行动计划", icon: ListTodo },
  { id: "materials", label: "素材库", icon: ClipboardList },
  { id: "followups", label: "HR 跟进", icon: MessagesSquare },
  { id: "contacts", label: "联系人", icon: Users },
  { id: "offers", label: "Offer 对比", icon: FileSpreadsheet },
  { id: "reviews", label: "面试复盘", icon: Mic },
  { id: "stats", label: "效果统计", icon: TrendingUp },
  { id: "privacy", label: "数据与隐私", icon: Download },
] as const

type TabId = (typeof TABS)[number]["id"]

// ── 页面 ──

export default function CareerCenterPage() {
  const [tab, setTab] = useState<TabId>("board")
  const { toast, showToast } = useToast()
  // 页面级加载一次岗位列表：任务/HR/Offer 创建时可关联岗位，形成完整岗位档案
  const [opportunities, setOpportunities] = useState<BoardRow[]>([])
  useEffect(() => { listBoard().then(setOpportunities).catch(() => undefined) }, [])

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-[var(--border-soft)] px-4 py-3 md:px-6">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-button-ink text-on-ink">
            <Compass className="h-4 w-4" />
          </span>
          <div>
            <h1 className="text-[15px] font-[600] text-ink">求职中心</h1>
            <p className="text-[11.5px] text-ink-faint">看板 · 行动 · 素材 · 跟进 · 复盘 · 统计</p>
          </div>
          <Button variant="ghost" size="icon" className="ml-auto h-[30px] w-[30px]" aria-label="刷新数据"
                  onClick={() => showToast("数据已刷新")}>
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
        <nav className="mt-2.5 flex gap-1 overflow-x-auto pb-0.5">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={cn(
                "flex shrink-0 items-center gap-1.5 rounded-[8px] px-2.5 py-1.5 text-[12.5px] transition-colors",
                tab === t.id ? "bg-surface-2 font-[560] text-ink" : "text-ink-faint hover:bg-[var(--hover)] hover:text-ink",
              )}
            >
              <t.icon className="h-3.5 w-3.5" /> {t.label}
            </button>
          ))}
        </nav>
      </header>
      <div className="flex-1 overflow-y-auto p-4 md:p-6">
        <div className="mx-auto w-full max-w-[1100px]">
          {tab === "board" && <BoardTab onToast={showToast} />}
          {tab === "tasks" && <TasksTab onToast={showToast} opportunities={opportunities} />}
          {tab === "materials" && <MaterialsTab onToast={showToast} />}
          {tab === "followups" && <FollowupsTab onToast={showToast} opportunities={opportunities} />}
          {tab === "contacts" && <ContactsTab onToast={showToast} opportunities={opportunities} />}
          {tab === "offers" && <OffersTab onToast={showToast} opportunities={opportunities} />}
          {tab === "reviews" && <ReviewsTab onToast={showToast} />}
          {tab === "stats" && <StatsTab />}
          {tab === "privacy" && <PrivacyTab onToast={showToast} />}
        </div>
      </div>
      <ToastBubble message={toast} />
    </div>
  )
}
