// mcp-jobs 启动包装器（只抓猎聘 liepin）：
// 1. 把 console.log（stdout）全部重定向到 stderr，保证 stdout 只输出 MCP JSON-RPC
// 2. 把 jobSearchUrls 裁成只留猎聘（其他平台反爬或不可靠，弃用）
// 启动：node mcp-servers/run-mcp-jobs.js
const origLog = console.log;
const origInfo = console.info;
console.log = (...args) => console.error(...args);
console.info = (...args) => console.error(...args);

// 只保留猎聘（liepin）
const { jobSearchUrls } = require('mcp-jobs/dist/config/urlConfig');
jobSearchUrls.length = 0;
jobSearchUrls.push({ url: 'https://www.liepin.com/zhaopin/', name: 'liepin' });

require('mcp-jobs/dist/mcp.js');
