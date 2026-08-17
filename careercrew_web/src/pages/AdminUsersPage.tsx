import { WorkspaceHeader } from "@/components/workspace/WorkspaceHeader"
import { UserManagementPanel } from "@/components/UserManagementPanel"

/** 独立的用户管理页（/admin/users 直达路由，内容与设置页「用户管理」区块一致）。 */
export default function AdminUsersPage() {
  return (
    <div className="flex h-full flex-col">
      <WorkspaceHeader
        title="用户管理"
        subtitle="开户、角色、启用/禁用与重置密码"
      />
      <div className="flex-1 overflow-y-auto px-6 py-4">
        <UserManagementPanel />
      </div>
    </div>
  )
}
