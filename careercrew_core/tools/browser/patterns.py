"""site-patterns：站点 URL 与 DOM 选择器集中定义（BossHunter 约定）。

反爬站点的前端会不定期改版——所有选择器只允许出现在本文件，
改版时只需更新此处，采集/解析逻辑不动。字段名与 JobsStore.upsert 对齐。
"""
from __future__ import annotations

BOSS_PATTERNS: dict = {
    # 搜索页（city 为空时用全国检索；城市代码见 zhipin 城市表，如北京 101010100）
    # 注意：Boss 会把 /web/geek/job 重定向到新版 /web/geek/jobs（左列表右详情布局）
    "search_url": "https://www.zhipin.com/web/geek/job?query={query}&city={city}",
    # 岗位卡片容器：2026 改版为 li.job-card-box；旧版 li/div.job-card-wrapper 兼容
    "job_card": "li.job-card-box, li.job-card-wrapper, div.job-card-wrapper",
    "wait_selector": "li.job-card-box .job-name, li.job-card-wrapper .job-name",
    "fields": {
        "title": "a.job-name, .job-name",
        "area": ".company-location, .job-area",       # 新版「广州·黄埔区·大沙」
        "salary": ".job-salary, .salary",
        "company": ".boss-name, .company-name a",     # 新版公司名在 boss-info 内
        "link": "a.job-name, a.job-card-left",        # 详情页 href（相对路径）
        # 经验/学历等标签（拼为 experience 字段）
        "experience": ".tag-list li, .filter-labels li",
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
