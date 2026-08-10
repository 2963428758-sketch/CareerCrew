// Boss直聘抓取 CLI（求职者侧 PC 版岗位搜索）
// connectOverCDP 复用本地已登录 Chrome（--remote-debugging-port=9222）的登录态，
// 截获 wapi/zpgeek/search/joblist.json 拿明文薪资，stdout 输出严格 JSON。
//
// 用法: node boss-cdp-cli.js --keyword Python [--city 101280100] [--pages 1] [--top 10]
// 输出: {"jobs":[{title,salary,company,city,experience,raw,tags,...}], "count":N, "error":null}
//
// 前置：Chrome 以 --remote-debugging-port=9222 启动且已登录 boss直聘。
// 错误降级：CDP 连不上/未登录 -> {"jobs":[],"error":"..."} exit 0
//
// 环境变量：BOSS_CDP_URL  CDP 端点（默认 http://localhost:9222）
const { chromium } = require('playwright');

const CDP_URL = process.env.BOSS_CDP_URL || 'http://localhost:9222';

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { keyword: '', city: '', pages: 1, top: 10 };
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--keyword') opts.keyword = args[++i] || '';
    else if (args[i] === '--city') opts.city = args[++i] || '';
    else if (args[i] === '--pages') opts.pages = parseInt(args[++i], 10) || 1;
    else if (args[i] === '--top') opts.top = parseInt(args[++i], 10) || 10;
  }
  return opts;
}

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

async function main() {
  const opts = parseArgs();
  if (!opts.keyword) {
    emit({ jobs: [], count: 0, error: 'missing --keyword' });
    return;
  }

  let browser;
  try {
    browser = await chromium.connectOverCDP(CDP_URL, { timeout: 5000 });
  } catch (e) {
    emit({
      jobs: [], count: 0,
      error: 'CDP未连接：请以 --remote-debugging-port=9222 启动 Chrome 并登录 boss直聘',
    });
    return;
  }

  let page;
  try {
    const ctx = browser.contexts()[0];
    // newPage 创建独立 page（最初验证成功的方式）
    page = await ctx.newPage();

    const allRaw = [];
    const seenIds = new Set();
    page.on('response', async (resp) => {
      const u = resp.url();
      if (u.includes('joblist')) {
        try {
          const json = await resp.json();
          const jl = (json && json.zpData && json.zpData.jobList) || [];
          for (const j of jl) {
            const k = j.encryptJobId || `${j.jobName}::${j.brandName}`;
            if (!seenIds.has(k)) { seenIds.add(k); allRaw.push(j); }
          }
        } catch {}
      }
    });

    for (let pageNum = 1; pageNum <= opts.pages; pageNum++) {
      const url =
        `https://www.zhipin.com/web/geek/job?query=${encodeURIComponent(opts.keyword)}` +
        (opts.city ? `&city=${opts.city}` : '') +
        `&page=${pageNum}`;
      const before = allRaw.length;
      // goto 重试（connectOverCDP + newPage 导航偶发 about:blank 不请求 joblist，重试提高成功率）
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
        } catch (e) {
          console.error(`[page ${pageNum} 尝试${attempt + 1}] goto err: ${e.message}`);
        }
        await page.waitForTimeout(6000);
        if (allRaw.length > before) break; // 截获到数据
        console.error(`[page ${pageNum} 尝试${attempt + 1}] allRaw=${allRaw.length}，重试`);
      }
      if (allRaw.length === before) break; // 重试3次仍无数据
      if (allRaw.length >= opts.top * 3) break; // 够了
    }

    // 字段映射（Boss joblist.json -> 统一结构，基于实测字段）
    const seen = new Set();
    const jobs = [];
    for (const j of allRaw) {
      const title = j.jobName || '';
      const company = j.brandName || '';
      const dedupKey = `${title}::${company}`;
      if (!title || seen.has(dedupKey)) continue;
      seen.add(dedupKey);
      const skills = j.skills || [];
      jobs.push({
        title,
        salary: j.salaryDesc || '',
        company,
        city: j.cityName || '',
        district: j.areaDistrict || '',
        experience: j.jobExperience || '',
        education: j.jobDegree || '',
        raw: [j.jobName, j.salaryDesc, j.brandName, j.cityName, j.jobExperience, j.jobDegree, skills.join('/')]
          .filter(Boolean).join(' ').slice(0, 500),
        tags: skills,
        welfare: j.welfareList || [],
        industry: j.brandIndustry || '',
        scale: j.brandScaleName || '',
        stage: j.brandStageName || '',
        url: j.encryptJobId ? `https://www.zhipin.com/job_detail/${j.encryptJobId}.html` : '',
      });
      if (jobs.length >= opts.top) break;
    }

    emit({ jobs, count: jobs.length, error: null });
  } catch (e) {
    emit({ jobs: [], count: 0, error: String(e && e.message ? e.message : e) });
  } finally {
    if (page) await page.close().catch(() => {});
    // connectOverCDP 的 close 只断开，不关闭用户的 Chrome
    await browser.close().catch(() => {});
  }
}

main();
