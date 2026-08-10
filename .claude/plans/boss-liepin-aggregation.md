# Boss直聘 + 猎聘 双平台岗位抓取封装

## 目标
把已验证的 Boss直聘 CDP 抓取(实证 15 岗/明文薪资)封装成 CareerCrew 岗位模块,与现有猎聘 mcp-jobs **并行抓取、合并去重**,统一字段输出。

## 现状(已探清)
- **猎聘**: `search_jobs_mcp()` → spawn `mcp-servers/run-mcp-jobs.js`(Node mcp-jobs)→ 返回 `{title,city,salary,experience,raw,source}`
- **search_jobs tool**(internal/search_jobs.py）: `search_jobs(direction, top_k)` → 只调猎聘
- **Boss**: `scripts/boss_cdp_jobs.js` 已验证跑通（CDP 复用登录态 + 截 `wapi/zpgeek/search/joblist.json` → 明文薪资），但输出是 console.log，非结构化、不可传参
- **调用链**: `JobMatcher` agent (ReAct) → `search_jobs` tool → `search_jobs_mcp`
- **测试**: `test_job_matcher.py` 注册真实 `search_jobs` tool，用 FakeChatModel 驱动

## 方案

### 1. 新建 `mcp-servers/boss-cdp-cli.js`（Node CLI，结构化输出）
改造自 `scripts/boss_cdp_jobs.js`：
- **CLI 参数**: `--keyword`(必填) `--city`(Boss城市代码，默认空=全国) `--pages`(默认1) `--top`(默认10)
- **逻辑**: `connectOverCDP(localhost:9222)` → 新页访问 `www.zhipin.com/web/geek/job?query=...&city=...` → 截获 `wapi/zpgeek/search/joblist.json` → 提取 `zData.jobList` → 多页合并
- **字段映射**（实施时按 API 实际字段做容错 `.get`）: `jobName→title`, `salaryDesc→salary`, `brandName→company`, `cityName→city`, `postDescription→raw`(截断500), `experienceName→experience`, `skills/jobLabels→tags`
- **stdout 严格 JSON**: `{"jobs":[{title,salary,company,city,experience,raw,tags}], "count":N, "error":null}`
- **错误降级**: CDP 连不上/未登录 → `{"jobs":[],"error":"CDP未连接或未登录"}`，**exit 0 不抛异常**（保证 Python 侧能解析）
- **关键**: 不关用户的 Chrome（`connectOverCDP` 的 close 只断开）

### 2. 新建 `careercrew_core/tools/jobs/boss_jobs.py`（Python 封装）
仿 `mcp_jobs.py` 模式：
- `search_jobs_boss(keyword, city="", top_k=10) -> list[dict]`
- subprocess 调 `node mcp-servers/boss-cdp-cli.js`，解析 stdout JSON
- 返回统一字段 `{title,city,salary,experience,raw,source:"boss"}`
- 异常/空/CDP未开 → 返回 `[]`（不阻塞，不抛异常）

### 3. 改 `careercrew_core/tools/internal/search_jobs.py`（并行聚合）
- `search_jobs(direction, top_k)` tool 改为**并行抓猎聘+Boss**
- 用 `concurrent.futures.ThreadPoolExecutor` 同时跑 `search_jobs_mcp` + `search_jobs_boss`
- **合并去重**: key = `(title归一化, company归一化)`，同公司同岗位只留一条（信息更全的优先）
- 每条带 `source` 标注（`"liepin"`/`"boss"`），输出里标注来源平台
- `top_k` 截断
- **优雅降级**: 任一平台失败/空 → 不影响另一个（猎聘 Chrome 没开时只剩猎聘，反之亦然）
- **tool 签名不变**（`direction, top_k`），保持 agent/测试兼容

### 4. 新建 `tests/unit/test_boss_jobs.py`
- mock subprocess，测 `boss_jobs.py` 的 JSON 解析 + 字段映射
- 测 CDP 未连接时降级（返回 `[]`）
- 测 `search_jobs` 聚合去重逻辑（mock 两个平台返回，验合并+去重+source标注）

### 5. 手动验证
- 启动 Chrome 9222 + 登录 Boss（登录态在 `C:\boss-chrome-profile`，不用重登）
- 跑 `search_jobs("Python", top_k=8)` 看两平台合并结果
- 验证猎聘单独可用（Boss Chrome 没开时）

## 不改动
- `run-mcp-jobs.js` / `mcp_jobs.py` 猎聘逻辑保持不变
- `search_jobs` tool 签名不变（`direction, top_k`）
- `job_matcher` agent 不变

## 运行时前提
- Boss 抓取需 Chrome 以 `--remote-debugging-port=9222` 启动且登录 Boss直聘
- 未开时 Boss 自动降级为空，猎聘正常工作

## 风险与应对
- Boss API 字段变 → 字段映射做 `.get` 容错 + 默认值
- Chrome 登录态过期 → 降级返回空 + error 提示
- 并行增加复杂度 → ThreadPoolExecutor 隔离，任一失败不阻塞
