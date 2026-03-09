from datetime import datetime, timezone, timedelta
from history import load_history, fetch_and_save_highfreq   # 新增 fetch_and_save_highfreq
from analyzer import (
    analyze_snapshot,          # 原有
    summarize_highfreq,        # 新增
    analyze_highfreq,          # 新增
    plot_highfreq,             # 新增
)
from notifier import send_text, send_highfreq_report         # 新增 send_highfreq_report
import json


# ──────────────────────────────────────────
# 原有函数（保持不变）
# ──────────────────────────────────────────
def run_report(slug: str):
    """原有快照报告，保持不变"""
    history = load_history(slug)
    if not history:
        send_text(f"[{slug}] 暂无历史数据")
        return
    latest = history[-1]
    analysis = analyze_snapshot(latest)
    send_text(f"📌 {slug}\n{analysis}")


# ──────────────────────────────────────────
# 新增：高频数据报告
# ──────────────────────────────────────────
def run_highfreq_report(slug: str, mode: str = "1min"):
    """
    拉取高频数据 → 统计分析 → AI解读 → 绘图 → 发送企业微信。

    slug : 市场 slug
    mode : "1min"（近1天）或 "5min"（近1周）
    """
    print(f"[report] 开始高频报告: slug={slug}, mode={mode}")

    # 1. 拉取并缓存高频数据
    df = fetch_and_save_highfreq(slug, mode=mode)
    if df.empty:
        send_text(f"⚠️ [{slug}] mode={mode} 未获取到高频数据")
        return

    # 2. 获取市场问题文本
    from fetcher import fetch_market
    import json as _json
    market   = fetch_market(slug)
    question = market.get("question", slug)

    # 3. 统计摘要
    summary = summarize_highfreq(df, mode=mode)

    # 4. AI 解读
    analysis = analyze_highfreq(question, summary)

    # 5. 绘图（返回 bytes，不写磁盘）
    chart_bytes = plot_highfreq(df, question, mode=mode)

    # 6. 发送企业微信
    send_highfreq_report(question, analysis, chart_bytes)

    print(f"[report] 高频报告已发送: {question} ({mode})")


# ──────────────────────────────────────────
# 新增：同时发送两种粒度的报告
# ──────────────────────────────────────────
def run_all_highfreq_reports(slugs: list):
    """
    对多个 slug 分别发送 1min（近1天）和 5min（近1周）报告。
    slugs : slug 列表，如 ["will-trump-be-president-on-july-4-2025"]
    """
    for slug in slugs:
        for mode in ["1min", "5min"]:
            try:
                run_highfreq_report(slug, mode=mode)
            except Exception as e:
                send_text(f"❌ [{slug}] mode={mode} 报告失败: {e}")
                print(f"[report] 错误: {e}")
