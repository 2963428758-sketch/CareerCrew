# Wave F 报告 — Task C1 / C2（前端）

## 状态：DONE_WITH_CONCERNS

## 提交哈希
- Task C1：`2819da8` — feat(web): admin users page with role guard and sidebar entry
- Task C2：`a275ff8` — feat(web): knowledge visibility UI (scope selector, badges, publish controls) and per-user data page

## 执行步骤情况（TDD）

### Task C1（`/admin/users` 用户管理页 + 角色守卫 + 导航）
1. 新建 `AdminUsersPage.test.tsx`（照计划照抄）。
2. 运行确认失败：`npx vitest run src/pages/AdminUsersPage.test.tsx` → FAIL（`Failed to resolve import "@/pages/AdminUsersPage"... Does the file exist?`），符合预期。
3. 新建 `AdminUsersPage.tsx`（照计划完整文件）。
4. `App.tsx`：lazy 注册 `AdminUsersPage`、`NAV` 数组类型加 `adminOnly?: boolean` 并新增「用户管理」项、渲染处 `NAV.filter(...)`、`PAGES` 加入口、页面渲染守卫、lucide 增加 `UserCog`（全部按计划精确替换）。
   - 注意：第一次 edit 加 `UserCog` 时遇到一次 `ReplaceFileW EIO (Win32 1175)`，重试同一条 edit 后成功；文件最终内容正确。
5. 测试/静态检查：`npx vitest run` 13/13 PASS；`npm run lint` 0 errors（2 个 pre-existing 警告 `react/only-export-components`，位于 `ui/button.tsx`、`ui/badge.tsx`，非本任务改动）；`npx tsc -b` PASS。
6. Commit `2819da8`。

### Task C2（知识库可见性前端）
1. 新建 `KnowledgePanel.test.tsx`（照计划照抄）。
2. 运行确认失败：`npx vitest run src/components/KnowledgePanel.test.tsx` → FAIL（真实面板尚未渲染新徽标/按钮），符合预期。
3. `types.ts`：追加 `KB_SCOPE` 常量。
4. `threadStore.ts`：`RetrievalScope` 联合类型扩为 `all | public | private | category`。
5. `KnowledgePanel.tsx`：import auth 快照 + `Globe`；`KnowledgeDoc` 扩展 `visibility`/`owner_user_id`；组件内 `me`/`isAdmin`/`uploadVisibility`；`handleUpload` FormData 加 `visibility`；`handleDelete` 加 403 处理 + 签名改为 `KnowledgeDoc`；新增 `togglePublish`；上传表单区加 admin 可见性开关；文档列表项 key 改 `doc.doc + doc.visibility`、加公共/我的徽标、操作区改发布/删除权限（全部按计划）。
6. `KnowledgePage.tsx`：import `KB_SCOPE`；加 `scope`/`changeScope`；scope chips 插在 `KB_CATEGORIES` chips 之前；`handleAsk` 的 `startStream` body 加 `scope`。
   - 注意：scope chips 插入这一步同样遇到一次 `ReplaceFileW EIO (Win32 1175)`，重试后成功。
7. `DataPage.tsx`：import `getAuthSnapshot`；三处 `"u_001"` → ``getAuthSnapshot().user?.id ?? "u_001"``（`:133` profile PUT、`:414` memory policy GET、`:459` memory policy PUT）。
8. 测试/静态检查：`npx vitest run` 14/14 PASS；`npm run lint` 0 errors（同 2 警告）；`npx tsc -b` PASS；`npm run build` 成功（1.76s）。build 有一条 `[INEFFECTIVE_DYNAMIC_IMPORT] DataPage.tsx...also statically imported by SettingsDialog.tsx`，为既有结构（与本任务无关），非错误。
9. Commit `a275ff8`。

## 偏离与顾虑（DONE_WITH_CONCERNS 的原因）

以下均因**计划自身测试代码块与其权威实现代码块互相矛盾**，无法两者同时照抄通过，故对「测试代码」做了最小适配（实现代码一律严格照计划、未改动）——

1. **C1 测试 `page_size` 断言不一致**：计划测试断言 `toHaveBeenCalledWith("/api/auth/users?page=1&page_size=20")`，而计划实现 `refresh()` 硬编码 `page_size=100`。保留实现（权威）不变，将测试断言改为 `page_size=100`（`AdminUsersPage.test.tsx:42`）。

2. **C1/C2 测试 `useSyncExternalStore` 无限循环**：计划测试的 `getAuthSnapshot` mock 每次返回新对象字面量 `() => ({...})`，违反 React `useSyncExternalStore`「getSnapshot 必须返回缓存引用」契约，触发 `Maximum update depth exceeded`。将快照对象缓存为模块级常量 `adminSnapshot` 并让 mock 返回该常量（语义不变，与真实 `@/lib/auth.ts` 模块级 `snapshot` 的稳定引用一致）。`AdminUsersPage.test.tsx` 与 `KnowledgePanel.test.tsx` 两处都改。

3. **C2 测试 `getByText("mine.pdf")` 多元素冲突**：计划测试 fixture `source` 与 `doc` 同为 `"mine.pdf"`，导致文档标题 `<span>` 与来源 basename `<p>` 都渲染 `"mine.pdf"`，`getByText` 报 "Found multiple elements"。将 fixture `source` 改为 `C:\uploads\mine_file.pdf` / `public_file.pdf`（basename ≠ doc 名），保留断言针对 doc 标题。

4. **C2 测试「发布到公共库」文案不存在**：计划的可见性开关默认 `uploadVisibility="private"`（初始文案「我的私有库」），「发布到公共库」仅作为 Globe 按钮的 `title` 属性（`getByText` 匹配不到）。为忠实原断言，先 `fireEvent.click(screen.getByText("我的私有库"))` 切到 public 态再断言「发布到公共库」。测试引入 `fireEvent`。

以上四点是「断言需适配实现契约/新字段交互」性质的测试侧最小改动，实现代码零偏离。

## 其他观察（非阻塞）
- 并行后端 agent 在两个 commit 之间插入了 `fbe9dca feat(auth): account store abstraction...`，但我的两个 commit 哈希不变、内容完整。
- 工作树中 `M careercrew_api/auth/service.py`、`M tests/unit/test_config_loading.py`（后者已消失）、`?? .superpowers/sdd/progress.md` 均为并行后端 agent / 其它非本任务产物，**未触碰**。
- 后端 publish/unpublish/scope 端点尚未上线，前端仅按契约 + mock 测试完成，未联调真实后端。

## 既有测试保持通过
`KnowledgePage.test.tsx`、`threadStore.test.ts`、`ConsultPage.test.tsx`、`MarkdownContent.test.tsx` 全部继续通过（`npx vitest run` 14/14）。
