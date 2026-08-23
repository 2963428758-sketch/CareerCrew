// mcp-jobs 启动包装器（只抓猎聘 liepin）：
// 1. 把 console.*（log/info/warn/error）全部重定向到日志文件 logs/mcp-jobs.log，
//    保证 stdout 只输出 MCP JSON-RPC（stdin/stdout 是协议通道，不能混入日志）。
// 2. 日志按大小轮转（默认 5MB），保留最近 KEEP_LOGS 份（默认 5），并清理超过
//    MAX_AGE_DAYS 天（默认 7）的轮转文件；启动时 + 每 10 分钟执行一次
//    （timer unref，不拖住进程在 stdin 关闭后退出）。
// 3. Error 只记 message + 栈前几行，大对象紧凑序列化，避免单条日志刷屏/撑爆文件。
// 4. 把 jobSearchUrls 裁成只留猎聘（其他平台反爬或不可靠，弃用）。
// 启动：node mcp-servers/run-mcp-jobs.js
const fs = require('fs');
const path = require('path');
const util = require('util');

const LOG_DIR = path.join(__dirname, '..', 'logs');
const LOG_FILE = path.join(LOG_DIR, 'mcp-jobs.log');
const MAX_LOG_BYTES = Math.max(1024, Number(process.env.MCP_JOBS_MAX_LOG_BYTES || 5 * 1024 * 1024));
const KEEP_LOGS = Math.max(1, Number(process.env.MCP_JOBS_KEEP_LOGS || 5));
const MAX_AGE_DAYS = Math.max(1, Number(process.env.MCP_JOBS_MAX_AGE_DAYS || 7));
const ROTATE_INTERVAL_MS = 10 * 60 * 1000;
const ERROR_STACK_LINES = 6;
const INSPECT_OPTS = { depth: 2, maxArrayLength: 20, breakLength: 160 };

function ensureLogDir() {
  try {
    fs.mkdirSync(LOG_DIR, { recursive: true });
  } catch (e) {
    // 日志目录创建失败不阻塞服务
  }
}

function rotateIfNeeded() {
  try {
    const st = fs.statSync(LOG_FILE);
    if (st.size >= MAX_LOG_BYTES) {
      const stamp = new Date().toISOString().replace(/[:.]/g, '-');
      fs.renameSync(LOG_FILE, `${LOG_FILE}.${stamp}`);
    }
  } catch (e) {
    // 文件不存在或并发进程同时轮转冲突，忽略
  }
}

function cleanOldLogs() {
  try {
    const files = fs
      .readdirSync(LOG_DIR)
      .filter((f) => f.startsWith('mcp-jobs.log') && f !== 'mcp-jobs.log');
    const cutoff = Date.now() - MAX_AGE_DAYS * 24 * 60 * 60 * 1000;
    const rotated = files
      .map((f) => {
        const p = path.join(LOG_DIR, f);
        try {
          return { f, p, m: fs.statSync(p).mtimeMs };
        } catch (e) {
          return null;
        }
      })
      .filter(Boolean)
      .sort((a, b) => b.m - a.m); // 新 -> 旧
    rotated.slice(KEEP_LOGS).forEach((x) => {
      try {
        fs.unlinkSync(x.p);
      } catch (e) {
        // 忽略
      }
    });
    rotated.filter((x) => x.m < cutoff).forEach((x) => {
      try {
        fs.unlinkSync(x.p);
      } catch (e) {
        // 忽略
      }
    });
  } catch (e) {
    // logs 目录不存在等情况忽略
  }
}

function rotateAndClean() {
  rotateIfNeeded();
  cleanOldLogs();
}

function fmtArg(a) {
  if (typeof a === 'string') {
    return a;
  }
  if (a instanceof Error) {
    // 只记 message + 栈前几行，避免整个 Error 对象展开刷屏
    return (a.stack || `Error: ${a.message}`).split('\n').slice(0, ERROR_STACK_LINES).join('\n');
  }
  try {
    return util.inspect(a, INSPECT_OPTS);
  } catch (e) {
    return String(a);
  }
}

function logLine(kind, args) {
  const ts = new Date().toISOString();
  const msg = args.map(fmtArg).join(' ');
  try {
    fs.appendFileSync(LOG_FILE, `[${ts}] [${kind}] ${msg}\n`);
  } catch (e) {
    // 日志写入失败不阻塞
  }
}

ensureLogDir();
rotateAndClean();
setInterval(rotateAndClean, ROTATE_INTERVAL_MS).unref();

console.error = (...args) => logLine('error', args);
console.warn = (...args) => logLine('warn', args);
console.log = (...args) => logLine('info', args);
console.info = (...args) => logLine('info', args);

// 只保留猎聘（liepin）
const { jobSearchUrls } = require('mcp-jobs/dist/config/urlConfig');
jobSearchUrls.length = 0;
jobSearchUrls.push({ url: 'https://www.liepin.com/zhaopin/', name: 'liepin' });

// 上游猎聘选择器偶尔改版；旧实现只要 title 一个选择器失败，就整卡退化成
// 无字段边界的 content，导致公司名丢失。这里把各字段改为独立容错抓取。
const { crawlerConfigs } = require('mcp-jobs/dist/config/crawlerConfig');
const liepinConfig = crawlerConfigs.find((item) => item.name === 'liepin');
if (liepinConfig?.rules?.jobInfo) {
  liepinConfig.rules.jobInfo.handler = async (currentData, value, element) => {
    const pickText = async (selectors) => {
      for (const selector of selectors) {
        try {
          const text = await element.$eval(selector, (el) => el.textContent?.trim() || '');
          if (text) return text;
        } catch (e) {
          // 当前选择器不存在，继续尝试兼容项
        }
      }
      return '';
    };
    const title = await pickText(['.job-title-box .ellipsis-1', '.job-title-box', '.job-title']);
    const salary = await pickText(['.job-salary', '.salary']);
    const company = await pickText(['.company-name', '.company-info .ellipsis-1']);
    const address = await pickText(['.job-dq-box', '.job-address', '.workplace']);
    let tags = [];
    try {
      tags = await element.$$eval(
        '.job-labels-box span, .company-tags-box span',
        (elements) => elements.map((el) => el.textContent?.trim() || '').filter(Boolean),
      );
    } catch (e) {
      // 标签不是必填字段
    }
    let jobDetail = '';
    try {
      jobDetail = await element.$eval('a', (el) => el.getAttribute('href') || '');
    } catch (e) {
      // 链接不是必填字段
    }
    if (title || salary || company || address) {
      return { title, salary, company, address, tags, jobDetail };
    }
    return { content: (await element.textContent()) || '' };
  };
}

require('mcp-jobs/dist/mcp.js');
