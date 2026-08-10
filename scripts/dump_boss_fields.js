// 诊断：dump Boss joblist.json 第一个 job 的完整字段，确认 salary 字段名
const path = require('path');
const { chromium } = require(path.join(__dirname, '..', 'mcp-servers', 'node_modules', 'playwright'));

(async () => {
  const browser = await chromium.connectOverCDP('http://localhost:9222', { timeout: 5000 });
  const ctx = browser.contexts()[0];
  let page = ctx.pages()[0];
  if (!page) page = await ctx.newPage();
  let captured;
  page.on('response', async (r) => {
    if (r.url().includes('zpgeek') && r.url().includes('joblist')) {
      try { captured = await r.json(); } catch {}
    }
  });
  await page.goto('about:blank', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await page.goto('https://www.zhipin.com/web/geek/job?query=Python&city=101280100&page=1', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(6000);
  if (captured) {
    const jobs = (captured.zpData && captured.zpData.jobList) || [];
    console.log('count:', jobs.length);
    if (jobs[0]) {
      console.log('keys:', Object.keys(jobs[0]).join(', '));
      console.log('full[0]:', JSON.stringify(jobs[0], null, 2));
    }
  } else {
    console.log('no joblist.json captured');
  }
  await browser.close();
})();
