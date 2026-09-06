import { Link } from "react-router-dom"
import { Briefcase } from "lucide-react"

import type { PreparationSession } from "@/lib/preparation"

/**
 * 准备会话横幅：在简历优化 / 面试练习页顶部明确展示当前使用的岗位与简历版本。
 * 点击「查看」跳到岗位准备页对应岗位。
 */
export function PreparationBanner({ session }: { session: PreparationSession }) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-[var(--border-soft)] bg-muted/40 px-4 py-2 text-[12px] md:px-6">
      <div className="flex min-w-0 items-center gap-1.5 text-ink-soft">
        <Briefcase className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">
          岗位准备：
          <span className="font-[560] text-ink">{session.company} · {session.title}</span>
          <span className="text-ink-faint">
            {" "}· 简历版本「{session.resume_label}」已自动带入
          </span>
        </span>
      </div>
      <Link
        to={`/preparation?opportunity=${encodeURIComponent(session.opportunity_id)}`}
        className="shrink-0 text-ink-faint hover:text-ink"
      >
        查看
      </Link>
    </div>
  )
}
