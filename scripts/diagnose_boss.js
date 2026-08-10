// 诊断 Boss直聘移动版搜索页真实状态：重定向？登录？验证码？选择器改版？
const path = require('path');
const { chromium } = require(path.join(__dirname, '..', 'mcp-servers', 'node_modules', 'playwright'));

(async () => {
  const browser = await chromium.launch({ headless: false });
  const ctx = await browser.newContext({
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
    viewport: { width: 375, height: 812 },
    locale: 'zh-CN',
  });
  const page = await ctx.newPage();

  page.on('response', (resp) => {
    const u = resp.url();
    if (u.includes('zhipin')) {
      console.log(`[resp] ${resp.status()} ${u.slice(0, 130)}`);
    }
  });

  const url = 'https://m.zhipin.com/c100010000/?page=1&query=Python';
  console.log('访问:', url);
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  } catch (e) {
    console.log('goto error:', e.message);
  }
  await page.waitForTimeout(5000);

  console.log('\n=== 最终 URL ===\n', page.url());
  console.log('=== 标题 ===', await page.title());
  console.log('=== li.item 数量 ===', await page.locator('li.item').count());
  console.log('=== .job-card 数量 ===', await page.locator('.job-card').count());

  const bodyText = await page.evaluate(() => document.body.innerText.slice(0, 1500));
  console.log('\n=== body 文本(前1500) ===\n', bodyText);

  console.log('\n=== 信号检测 ===');
  console.log('含"登录":', bodyText.includes('登录'));
  console.log('含"验证":', bodyText.includes('验证'));
  console.log('含"安全":', bodyText.includes('安全'));
  console.log('含"Python":', bodyText.includes('Python'));
  console.log('含"职位":', bodyText.includes('职位'));

  await page.screenshot({ path: path.join(__dirname, 'boss_diagnose.png'), fullPage: true });
  console.log('\n截图已存: scripts/boss_diagnose.png');

  await page.waitForTimeout(3000);
  await browser.close();
})();
