// mcp-jobs 启动包装器（只抓 Boss直聘 zhipin 移动版）：
// 1. 把 console.log（stdout）重定向到 stderr，保证 stdout 只输出 MCP JSON-RPC
// 2. jobSearchUrls 只留 zhipin（验证 Boss 直聘能否抓到岗位）
// 启动：node mcp-servers/run-mcp-jobs-boss.js
const origLog = console.log;
const origInfo = console.info;
console.log = (...args) => console.error(...args);
console.info = (...args) => console.error(...args);

// 只保留 Boss直聘（zhipin 移动版，c100010000=北京）
const { jobSearchUrls } = require('mcp-jobs/dist/config/urlConfig');
jobSearchUrls.length = 0;
jobSearchUrls.push({ url: 'https://m.zhipin.com/c100010000', name: 'zhipin' });

require('mcp-jobs/dist/mcp.js');
