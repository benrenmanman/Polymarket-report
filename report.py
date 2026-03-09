from datetime import datetime, timezone, timedelta
from history import fetch_highfreq
from fetcher import fetch_market
from analyzer import (
    analyze_snapshot,
    summarize_highfreq,
    analyze_highfreq,
    plot_highfreq,
)
from notifier import send_text, send_highfreq_report


# ──────────────────────────────────────────
# 原有函数：快照报告（改为直接从API获取当前数据）
# ──────────────────────────────────────────
def run_report(slug: str):
    """实时拉取当前市场快照并分析"""
    market = fetch_market(slug)
    if not market:
        send_text(f"[{slug}] 无法获取市场数据")
        return
    analysis = analyze_snapshot(market)
    send_text(f"📌 {slug}\n{analysis}")


# ──────────────────────────────────────────
# 高频数据报告（改为纯API拉取，不写缓存）
# ──────────────────────────────────────────
def run_highfreq_report(slug: str, mode: str = "1min"):
    """
    拉取高频数据 → 统计分析 → AI解读 → 绘图 → 发送企业微信。
    slug : 市场 slug
    mode : "1min"（近1天）或 "5min"（近1周）
    """
    print(f"[report] 开始高频报告: slug={slug}, mode={mode}")

    # 1. 直接从 API 拉取高频数据（不缓存）
    df = fetch_highfreq(slug, mode=mode)
    if df.empty:
        send_text(f"⚠️ [{slug}] mode={mode} 未获取到高频数据")
        return

    # 2. 获取市场问题文本
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
# 批量发送多个 slug 的双粒度报告
# ──────────────────────────────────────────
def run_all_highfreq_reports(slugs: list):
    """
    对多个 slug 分别发送 1min（近1天）和 5min（近1周）报告。
    """
    for slug in slugs:
        for mode in ["1min", "5min"]:
            try:
                run_highfreq_report(slug, mode=mode)
            except Exception as e:
                send_text(f"❌ [{slug}] mode={mode} 报告失败: {e}")
                print(f"[report] 错误: {e}")
