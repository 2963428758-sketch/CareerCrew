import { lazy, Suspense, useEffect, useState, useSyncExternalStore, type ComponentType } from "react"
import { useLocation } from "react-router-dom"
import { Menu } from "lucide-react"
import { cn } from "@/lib/utils"
import { useThreadStore } from "@/store/threadStore"
import { useStreamStore } from "@/store/streamStore"
import { AppSidebar } from "@/components/app-shell/AppSidebar"
import { SettingsSidebar } from "@/components/app-shell/SettingsSidebar"
import { Tooltip } from "@/components/ui/tooltip"
import { AuthLoading, AuthScreen } from "@/components/AuthScreen"
import PasswordChangeScreen from "@/components/PasswordChangeScreen"
import { getAuthSnapshot, restoreSession, subscribeAuth } from "@/lib/auth"

// 路由懒加载：按页拆 chunk，消除首屏大 bundle（Chat/Consult/Knowledge 等重页面按需加载）
const ChatPage = lazy(() => import("@/pages/ChatPage"))
const MatcherPage = lazy(() => import("@/pages/MatcherPage"))
const InterviewPage = lazy(() => import("@/pages/InterviewPage"))
const ResumePage = lazy(() => import("@/pages/ResumePage"))
const KnowledgePage = lazy(() => import("@/pages/KnowledgePage"))
const ConsultPage = lazy(() => import("@/pages/ConsultPage"))
const SettingsPage = lazy(() => import("@/pages/SettingsPage"))
const AdminUsersPage = lazy(() => import("@/pages/AdminUsersPage"))

const PAGES: Record<string, ComponentType> = {
  "/": ChatPage,
  "/matcher": MatcherPage,
  "/interview": InterviewPage,
  "/resume": ResumePage,
  "/knowledge": KnowledgePage,
  "/consult": ConsultPage,
  "/admin/users": AdminUsersPage,
}

type Viewport = "wide" | "narrow" | "mobile"

const viewportOf = (): Viewport =>
  window.innerWidth < 768 ? "mobile" : window.innerWidth < 1100 ? "narrow" : "wide"

export default function App() {
  const auth = useSyncExternalStore(subscribeAuth, getAuthSnapshot, getAuthSnapshot)
  const location = useLocation()
  const [viewport, setViewport] = useState<Viewport>(viewportOf)
  /** 手动收起/展开；null = 跟随视口（窄屏自动收起，宽屏展开） */
  const [collapsedOverride, setCollapsedOverride] = useState<boolean | null>(null)
  const [mobileOpen, setMobileOpen] = useState(false)
  /** 设置页当前区块（侧边栏与内容区共享） */
  const [settingsSection, setSettingsSection] = useState("profile")

  useEffect(() => { void restoreSession() }, [])

  useEffect(() => {
    const onResize = () => setViewport(viewportOf())
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [])

  // 登出/切换用户：清空会话与线程状态（各 store 里可能残留上一个用户的数据）
  const userId = auth.user?.id
  useEffect(() => {
    useThreadStore.getState().resetAll()
    useStreamStore.getState().resetAll()
  }, [userId])

  if (auth.status === "loading") return <AuthLoading />
  if (auth.status === "anonymous") return <AuthScreen />
  // 新建/重置密码的账号：完成强制改密前只能看到改密页（后端业务 API 同步 403 兜底）
  if (auth.user?.must_change_password) return <PasswordChangeScreen />

  // 设置页是独立页面：不渲染主侧边栏（页面自带设置导航侧边栏）
  const isSettings = location.pathname === "/settings"
  const collapsed = collapsedOverride ?? viewport === "narrow"

  return (
    /* Application Shell：暖灰外壳，Sidebar 直接长在背景上，Workspace 是浮起的白色圆角面板 */
    <div
      className={cn(
        "relative flex h-screen w-screen overflow-hidden bg-shell",
        "p-2 gap-2",
        "min-[1440px]:p-2.5 min-[1440px]:gap-2.5",
        "min-[1600px]:p-3 min-[1600px]:gap-3",
        "max-md:gap-0 max-md:p-0"
      )}
    >
      {isSettings ? (
        <SettingsSidebar
          collapsed={collapsed}
          onToggleCollapsed={() => setCollapsedOverride(!collapsed)}
          overlay={viewport === "mobile"}
          overlayOpen={mobileOpen}
          onOverlayClose={() => setMobileOpen(false)}
          section={settingsSection}
          onSelectSection={setSettingsSection}
        />
      ) : (
        <AppSidebar
          collapsed={collapsed}
          onToggleCollapsed={() => setCollapsedOverride(!collapsed)}
          overlay={viewport === "mobile"}
          overlayOpen={mobileOpen}
          onOverlayClose={() => setMobileOpen(false)}
          auth={auth.user}
        />
      )}

      {/* 移动端：左上角导航触发按钮 */}
      {viewport === "mobile" && (
        <Tooltip label="打开导航">
          <button
            onClick={() => setMobileOpen(true)}
            aria-label="打开导航"
            className="absolute left-3 top-3 z-30 flex h-[30px] w-[30px] items-center justify-center rounded-[7px] border border-[var(--border-soft)] bg-workspace text-ink shadow-prompt transition-colors duration-100 hover:bg-surface-2"
          >
            <Menu className="h-4 w-4" strokeWidth={1.7} />
          </button>
        </Tooltip>
      )}

      {/* Floating Workspace：整块白色画布，17px 圆角 + 微边框 + 极轻阴影 */}
      <main
        className={cn(
          "relative min-w-0 flex-1 overflow-hidden rounded-[17px] border border-[var(--border-soft)] bg-workspace shadow-workspace",
          "max-md:rounded-none max-md:border-0 max-md:shadow-none"
        )}
      >
        <Suspense
          fallback={
            <div className="flex h-full items-center justify-center text-[13px] text-ink-soft">
              页面加载中…
            </div>
          }
        >
          {isSettings ? (
            <SettingsPage section={settingsSection} />
          ) : (
            (() => {
              const requested = PAGES[location.pathname] ?? ChatPage
              const Page =
                location.pathname === "/admin/users" && auth.user?.role !== "admin"
                  ? ChatPage
                  : requested
              return <Page key={location.pathname} />
            })()
          )}
        </Suspense>
      </main>
    </div>
  )
}
