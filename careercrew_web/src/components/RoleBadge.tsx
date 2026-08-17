import { ShieldCheck } from "lucide-react"
import { cn } from "@/lib/utils"

/** 角色徽标：管理员绿底 + 盾牌；普通用户灰底。 */
export function RoleBadge({ role, className }: { role: string; className?: string }) {
  const admin = role === "admin"
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-[5px] px-1.5 py-0.5 text-[11px] font-medium",
        admin
          ? "bg-primary/10 text-primary"
          : "bg-[#e9e9e4] text-[#66665f] dark:bg-[#3b3b38] dark:text-[rgba(255,255,255,0.65)]",
        className
      )}
    >
      {admin && <ShieldCheck className="h-3 w-3" />}
      {admin ? "管理员" : "普通用户"}
    </span>
  )
}
