// CDP 复用真实登录态抓取 Boss直聘 PC 版岗位（截 API 明文 + 解析 DOM 双路）
// 前提：Chrome 以 --remote-debugging-port=9222 启动且已登录 boss直聘
const path = require('path');
const { chromium } = require(path.join(__dirname, '..', 'mcp-servers', 'node_modules', 'playwright'));

const CDP_URL = 'http://localhost:9222';
// 101280100=广州 101010100=北京 101020100=上海
const SEARCH_URL = 'https://www.zhipin.com/web/geek/job?query=Python&city=101280100';

(async () => {
  // 1. 连接 CDP（复用真实登录态）
  let browser;
  try {
    browser = await chromium.connectOverCDP(CDP_URL, { timeout: 5000 });
    console.log('✅ 已连接 CDP:', CDP_URL);
  } catch (e) {
    console.log('❌ 无法连接 CDP', CDP_URL);
    console.log('请先启动带 debug 端口的 Chrome 并登录 boss直聘：');
    console.log('  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222 --user-data-dir=C:\\boss-chrome-profile');
    process.exit(1);
  }

  const ctx = browser.contexts()[0];
  const page = await ctx.newPage();

  // 2. 截获搜索 API（拿明文薪资）
  const apiHits = [];
  page.on('response', async (resp) => {
    const u = resp.url();
    if (u.includes('zpgeek') && (u.includes('search') || u.includes('joblist'))) {
      try {
        const json = await resp.json();
        apiHits.push({ url: u, json });
        console.log('[API 截获]', resp.status(), u.slice(0, 110));
      } catch {}
    }
  });

  // 3. 访问 PC 版搜索页
  console.log('\n访问:', SEARCH_URL);
  try {
    await page.goto(SEARCH_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
  } catch (e) {
    console.log('goto error:', e.message);
  }
  await page.waitForTimeout(6000);

  console.log('最终URL:', page.url());
  console.log('标题:', await page.title());

  // 跳登录页了？
  const onLogin = page.url().includes('/web/user') || page.url().includes('login');
  console.log('是否跳登录页:', onLogin);

  // 4. 解析 DOM 岗位卡片（PC 版多选择器兜底）
  const domJobs = await page.evaluate(() => {
    const sels = ['.job-card-wrapper', '.search-job-result .job-card-left', 'li.job-card', '.job-list li'];
    let cards = [];
    for (const s of sels) {
      cards = document.querySelectorAll(s);
      if (cards.length) break;
    }
    return Array.from(cards).map((c) => ({
      text: c.innerText.replace(/\n+/g, ' | ').slice(0, 300),
    }));
  });
  console.log('\n=== DOM 岗位数:', domJobs.length, '===');
  domJobs.slice(0, 5).forEach((j, i) => console.log(`\n[${i + 1}]`, j.text));

  // 5. 从截获的 API 提取明文岗位
  console.log('\n=== API 截获数:', apiHits.length, '===');
  let apiJobs = [];
  for (const a of apiHits) {
    const jl = a.json?.zpData?.jobList || a.json?.data?.jobList || [];
    if (jl.length) { apiJobs = jl; break; }
  }
  console.log('API 岗位数:', apiJobs.length);
  apiJobs.slice(0, 5).forEach((j) =>
    console.log(JSON.stringify({ jobName: j.jobName, salaryDesc: j.salaryDesc, brandName: j.brandName, cityName: j.cityName }, null, 2))
  );

  await page.screenshot({ path: path.join(__dirname, 'boss_cdp_shot.png'), fullPage: true });
  console.log('\n截图: scripts/boss_cdp_shot.png');

  await page.close();
  await browser.close(); // connectOverCDP 只断开，不关用户的 Chrome
})();
