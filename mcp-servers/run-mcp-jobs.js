// mcp-jobs 启动包装器：把 console.log（stdout）全部重定向到 stderr，
// 保证 stdout 只输出 MCP JSON-RPC，不污染协议。
// 启动：node mcp-servers/run-mcp-jobs.js
const origLog = console.log;
const origInfo = console.info;
console.log = (...args) => console.error(...args);
console.info = (...args) => console.error(...args);

require('mcp-jobs/dist/mcp.js');
