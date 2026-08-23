"""site-patterns：站点 URL 与 DOM 选择器集中定义（BossHunter 约定）。

反爬站点的前端会不定期改版——所有选择器只允许出现在本文件，
改版时只需更新此处，采集/解析逻辑不动。字段名与 JobsStore.upsert 对齐。
"""
from __future__ import annotations

BOSS_PATTERNS: dict = {
    # 搜索页（city 为空时用全国检索；城市代码见 zhipin 城市表，如北京 101010100）
    "search_url": "https://www.zhipin.com/web/geek/job?query={query}&city={city}",
    # 岗位卡片容器（2024-2026 改版后为 li.job-card-wrapper；旧版 div.job-card-wrapper 兼容）
    "job_card": "li.job-card-wrapper, div.job-card-wrapper",
    "wait_selector": "li.job-card-wrapper .job-name, div.job-card-wrapper .job-name",
    "fields": {
        "title": ".job-name",
        "area": ".job-area",
        "salary": ".salary",
        "company": ".company-name a",
        "link": "a.job-card-left",          # 取 href 属性
        # 经验/学历等标签（拼为 experience 字段）
        "experience": ".filter-labels li",
    },
    # 未登录/风控验证页特征：命中即判定渠道不可用而非空结果
    "block_markers": [".nc_iconfont.btn_slide", "#wrap .btn-next", "text=安全验证"],
}

# 消息页（N2 投递打招呼 / E 批次 HR 回复监听复用）
BOSS_MESSAGE_PATTERNS: dict = {
    "message_url": "https://www.zhipin.com/web/geek/chat",
    "send_box": "#chat-input",
    "send_btn": ".btn-send",
    "msg_bubble_sent": ".message-system .my-message, .msg-item.self .text",
}
