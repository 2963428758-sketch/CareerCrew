"""高斯节流（N1）：人类化随机延迟。

固定间隔是自动化检测的最强特征；这里用正态分布采样动作间延迟，
并 clamp 到合理区间避免偶发的超长/零延迟。参考 BossHunter 的节流策略。
"""
from __future__ import annotations

import random
import time

# 默认节奏：均值 1.2s、σ 0.4s，clamp [0.3s, 5s]——足够慢显得像人，不至于拖垮采集
DEFAULT_MEAN_MS = 1200
DEFAULT_SIGMA_MS = 400
CLAMP_LO_MS = 300
CLAMP_HI_MS = 5000


def gauss_delay_ms(
    mean_ms: float = DEFAULT_MEAN_MS,
    sigma_ms: float = DEFAULT_SIGMA_MS,
    lo_ms: float = CLAMP_LO_MS,
    hi_ms: float = CLAMP_HI_MS,
) -> int:
    """采样一次人类化延迟（毫秒）。"""
    return int(max(lo_ms, min(hi_ms, random.gauss(mean_ms, sigma_ms))))


def human_pause(mean_ms: float = DEFAULT_MEAN_MS, sigma_ms: float = DEFAULT_SIGMA_MS) -> None:
    """同步休眠一次高斯延迟（浏览器动作之间调用）。"""
    time.sleep(gauss_delay_ms(mean_ms, sigma_ms) / 1000)
