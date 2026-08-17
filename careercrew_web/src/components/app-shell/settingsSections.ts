import type { ComponentType } from "react"
import { Brain, Info, Settings, User } from "lucide-react"

/** 设置页区块定义（侧边栏导航与内容页共用）。adminOnly 区块仅管理员可见。 */
export const SETTINGS_SECTIONS: {
  key: string
  label: string
  desc: string
  icon: ComponentType<{ className?: string; strokeWidth?: number }>
  adminOnly?: boolean
}[] = [
  { key: "profile", label: "能力画像", desc: "方向、技能、求职方向与目标公司", icon: User },
  { key: "memory", label: "记忆", desc: "已沉淀的语义事实与情景事件", icon: Brain },
  { key: "memory-settings", label: "记忆设置", desc: "全局开关与我的记忆策略", icon: Settings },
  { key: "account", label: "账号", desc: "头像、账号信息与密码修改", icon: Info },
  { key: "about", label: "关于", desc: "版本与应用信息", icon: Info },
]
