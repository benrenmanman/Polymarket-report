import json
import re
from datetime import datetime, timezone
from history import fetch_highfreq
from fetcher import fetch_market, fetch_markets_batch
from analyzer import (
    analyze_snapshot,
    summarize_highfreq,
    analyze_highfreq,
    plot_highfreq,
)
from notifier import send_text, send_markdown, send_markdown_v2, send_highfreq_report
from config import SLUGS


# ─────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────
def _extract_token_id(market: dict) -> str | None:
    token_ids = market.get("clobTokenIds", [])
    if isinstance(token_ids, str):
        try:
            token_ids = json.loads(token_ids)
        except Exception:
            return None
    return token_ids[0] if token_ids else None


def _get_yes_price(market: dict) -> float | None:
    """
    安全提取 Yes 价格。
    outcomePrices 在部分市场里是 JSON 字符串而非 dict，统一处理。
    字段完全缺失或无 Yes 键时返回 None。
    """
    raw = market.get("outcomePrices")
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None
    if not isinstance(raw, dict):
        return None
    val = raw.get("Yes")
    return float(val) if val is not None else None


_MONTH_MAP = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}


def _short_label(question: str) -> str:
    """从问题文本提取短时间标签，如 'by March 31' → '3/31'"""
    m = re.search(r"by (\w+)\s+(\d+)", question)
    if m:
        mn = _MONTH_MAP.get(m.group(1), m.group(1))
        return f"{mn}/{m.group(2)}"
    m2 = re.search(r"before (\d{4})", question)
    if m2:
        return f"<{m2.group(1)}"
    # fallback：取问题最后16个字符
    return question.split("?")[0].strip()[-16:]


def _trend(yes: float, day_change: float | None) -> str:
    """根据 oneDayPriceChange 返回趋势箭头"""
    if day_change is None:
        return "-"
    if day_change > 0.005:
        return "↑"
    if day_change < -0.005:
        return "↓"
    return "→"


# ─────────────────────────────────────────────────────
# 核心：构建 markdown_v2 汇总消息
# ─────────────────────────────────────────────────────
def build_summary_report(markets: dict) -> str:
    """
    将所有 slug 的最新价格汇总为一条 markdown_v2 消息（含表格）。
    markets : {slug: market_data}，market_data 可为 dict 或 list
    """
    now = datetime.now(timezone.utc).strftime("%m-%d %H:%M UTC")
    lines = [
        "# 📊 Polymarket 快报",
        f"> 更新时间：{now}",
        "",
    ]

    for slug, market in markets.items():
        if not market:
            lines += [f"### ⚠️ {slug}", "> 数据获取失败", ""]
            continue

        if isinstance(market, list):
            # ── 多选项市场：用表格展示 ──
            title = market[0].get("question", slug).rsplit(" by ", 1)[0]
            lines += [
                f"### {title}",
                "",
                "| 截止日期 | Yes 概率 | 趋势 | 24h 成交量 |",
                "| :------: | :------: | :--: | ---------: |",
            ]
            for sub in market:
                label      = _short_label(sub.get("question", ""))
                yes        = _get_yes_price(sub)           # ← 安全提取
                vol24      = sub.get("volume24hr") or 0
                day_change = sub.get("oneDayPriceChange")
                arrow      = _trend(yes, day_change) if yes is not None else "-"
                yes_str    = f"**{yes:.1%}**" if yes is not None else "N/A"
                vol_str    = f"${vol24:,.0f}" if vol24 else "-"
                lines.append(f"| {label} | {yes_str} | {arrow} | {vol_str} |")
            lines.append("")

        else:
            # ── 单市场 ──
            q          = market.get("question", slug)
            yes        = _get_yes_price(market)             # ← 安全提取
            vol24      = market.get("volume24hr") or 0
            day_change = market.get("oneDayPriceChange")
            arrow      = _trend(yes, day_change) if yes is not None else "-"
            yes_str    = f"**{yes:.1%}**" if yes is not None else "N/A"
            vol_str    = f"${vol24:,.0f}" if vol24 else "-"

            lines += [
                f"### {q}",
                "",
                "| Yes 概率 | 趋势 | 24h 成交量 |",
                "| :------: | :--: | ---------: |",
                f"| {yes_str} | {arrow} | {vol_str} |",
                "",
            ]

    lines += ["---", "> 每20分钟自动更新"]

    content = "\n".join(lines)

    # markdown_v2 限制 4096 字节，超出时裁剪并提示
    encoded = content.encode("utf-8")
    if len(encoded) > 4000:
        content = encoded[:4000].decode("utf-8", errors="ignore") + "\n\n> ⚠️ 内容过长已截断"

    return content


# ─────────────────────────────────────────────────────
# 详细高频报告（保留，供按需调用）
# ─────────────────────────────────────────────────────
def _run_single_highfreq(question: str, token_id: str, mode: str):
    df = fetch_highfreq(token_id, mode=mode)
    if df.empty:
        send_text(f"⚠️ [{question}] mode={mode} 未获取到高频数据")
        return
    summary     = summarize_highfreq(df, mode=mode)
    analysis    = analyze_highfreq(question, summary)
    chart_bytes = plot_highfreq(df, question, mode=mode)
    send_highfreq_report(question, analysis, chart_bytes)
    print(f"[report] 高频报告已发送: {question} ({mode})")


def build_report(slug: str, market, df_1min, df_5min):
    """发送单个 slug 的详细高频报告（由 fetch_job 按需调用）"""
    subs = market if isinstance(market, list) else [market]
    for sub in subs:
        question = sub.get("question", slug)
        token_id = _extract_token_id(sub)
        if not token_id:
            continue
        for mode, df in [("1min", df_1min), ("5min", df_5min)]:
            if df is not None and not df.empty:
                try:
                    summary     = summarize_highfreq(df, mode=mode)
                    analysis    = analyze_highfreq(question, summary)
                    chart_bytes = plot_highfreq(df, question, mode=mode)
                    send_highfreq_report(question, analysis, chart_bytes)
                    print(f"[report] 高频报告已发送: {question} ({mode})")
                except Exception as e:
                    send_text(f"❌ [{question}] mode={mode} 失败: {e}")


# ─────────────────────────────────────────────────────
# 快照报告（保留原有功能）
# ─────────────────────────────────────────────────────
def run_report(slug: str):
    market = fetch_market(slug)
    if not market:
        send_text(f"[{slug}] 无法获取市场数据")
        return
    m = market[0] if isinstance(market, list) else market
    analysis = analyze_snapshot(m)
    send_text(f"📌 {slug}\n{analysis}")


# ─────────────────────────────────────────────────────
# 独立运行入口（report.yml 触发 → 只发汇总）
# ─────────────────────────────────────────────────────
if __name__ == "__main__":
    print("[report] 开始执行")
    markets = fetch_markets_batch(SLUGS)
    summary_text = build_summary_report(markets)
    result = send_markdown_v2(summary_text)
    print(f"[report] 汇总消息已发送，返回：{result}")
