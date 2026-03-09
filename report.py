import json
from datetime import datetime, timezone, timedelta
from history import fetch_highfreq
from fetcher import fetch_market
from analyzer import (
    analyze_snapshot,
    summarize_highfreq,
    analyze_highfreq,
    plot_highfreq,
)
from notifier import (
    send_text, 
    send_template_card_report,
    upload_image
)
from config import SLUGS


# ──────────────────────────────────────────
# 内部工具：从市场 dict 提取 token_id
# ──────────────────────────────────────────
def _extract_token_id(market: dict) -> str | None:
    token_ids = market.get("clobTokenIds", [])
    if isinstance(token_ids, str):
        token_ids = json.loads(token_ids)
    return token_ids[0] if token_ids else None


# ──────────────────────────────────────────
# 整合单个市场的完整报告（快照 + 1min + 5min）
# ──────────────────────────────────────────
def build_integrated_report(slug: str) -> dict:
    """
    构建单个市场的完整报告数据
    返回：{
        "title": "市场标题",
        "snapshot": "快照分析",
        "sections": [{"title": "1min 分析", "content": "..."}],
        "charts": [bytes, bytes]  # 图表数据
    }
    """
    market = fetch_market(slug)
    if not market:
        return None
    
    # 处理多选项市场（取第一个）
    m = market[0] if isinstance(market, list) else market
    question = m.get("question", slug)
    token_id = _extract_token_id(m)
    
    if not token_id:
        return None
    
    # 1. 快照分析
    snapshot = analyze_snapshot(m)
    
    # 2. 高频数据分析
    sections = []
    charts = []
    
    for mode in ["1min", "5min"]:
        try:
            df = fetch_highfreq(token_id, mode=mode)
            if df.empty:
                continue
            
            # 统计摘要
            summary = summarize_highfreq(df, mode=mode)
            
            # AI 分析
            analysis = analyze_highfreq(question, summary)
            
            # 图表
            chart_bytes = plot_highfreq(df, question, mode=mode)
            
            sections.append({
                "title": f"📈 {mode.upper()} 分析",
                "content": analysis[:100] + "..."  # 截取前100字符
            })
            charts.append(chart_bytes)
            
        except Exception as e:
            print(f"[report] {slug} {mode} 分析失败: {e}")
            continue
    
    return {
        "title": question,
        "snapshot": snapshot,
        "sections": sections,
        "charts": charts
    }


# ──────────────────────────────────────────
# 发送整合的模板卡片报告
# ──────────────────────────────────────────
def send_integrated_card_report(slug: str):
    """
    为单个市场生成并发送整合的模板卡片
    """
    print(f"[report] 开始生成整合报告: {slug}")
    
    report_data = build_integrated_report(slug)
    if not report_data:
        send_text(f"❌ [{slug}] 无法生成报告")
        return
    
    # 上传图表
    chart_media_ids = []
    for chart_bytes in report_data["charts"]:
        try:
            media_id = upload_image(chart_bytes)
            chart_media_ids.append(media_id)
        except Exception as e:
            print(f"[report] 图表上传失败: {e}")
    
    # 构建卡片内容
    sections = [
        {"title": "📊 市场快照", "content": report_data["snapshot"][:50] + "..."}
    ]
    sections.extend(report_data["sections"])
    
    # 发送模板卡片
    send_template_card_report(
        title=report_data["title"],
        summary=f"包含快照分析 + {len(report_data['charts'])} 个时间粒度的数据分析",
        sections=sections,
        chart_media_ids=chart_media_ids
    )
    
    print(f"[report] ✓ 整合报告已发送: {slug}")


# ──────────────────────────────────────────
# 批量发送整合报告
# ──────────────────────────────────────────
def run_all_integrated_reports(slugs: list):
    """
    为所有 slug 生成整合的模板卡片报告
    """
    for idx, slug in enumerate(slugs, 1):
        try:
            print(f"\n[report] [{idx}/{len(slugs)}] 处理 {slug}")
            send_integrated_card_report(slug)
        except Exception as e:
            send_text(f"❌ [{slug}] 报告生成失败: {str(e)}")
            print(f"[report] 错误: {e}")


# ──────────────────────────────────────────
# 保留原有函数（向后兼容）
# ──────────────────────────────────────────
def _run_single_highfreq(question: str, token_id: str, mode: str):
    df = fetch_highfreq(token_id, mode=mode)
    if df.empty:
        send_text(f"⚠️ [{question}] mode={mode} 未获取到高频数据")
        return

    summary     = summarize_highfreq(df, mode=mode)
    analysis    = analyze_highfreq(question, summary)
    chart_bytes = plot_highfreq(df, question, mode=mode)
    
    # 使用旧方式发送
    from notifier import send_highfreq_report
    send_highfreq_report(question, analysis, chart_bytes)
    print(f"[report] 高频报告已发送: {question} ({mode})")


def run_report(slug: str):
    market = fetch_market(slug)
    if not market:
        send_text(f"[{slug}] 无法获取市场数据")
        return
    m = market[0] if isinstance(market, list) else market
    analysis = analyze_snapshot(m)
    send_text(f"📌 {slug}\n{analysis}")


def run_highfreq_report(slug: str, mode: str = "1min"):
    print(f"[report] 开始高频报告: slug={slug}, mode={mode}")
    market = fetch_market(slug)

    if isinstance(market, list):
        print(f"[report] 多选项市场，共 {len(market)} 个选项")
        for sub in market:
            question = sub.get("question", slug)
            token_id = _extract_token_id(sub)
            if not token_id:
                print(f"[report] 跳过无 token_id 的子市场: {question}")
                continue
            try:
                _run_single_highfreq(question, token_id, mode)
            except Exception as e:
                send_text(f"❌ [{question}] mode={mode} 子市场报告失败: {e}")
                print(f"[report] 子市场错误: {e}")
    else:
        question = market.get("question", slug)
        token_id = _extract_token_id(market)
        if not token_id:
            send_text(f"⚠️ [{slug}] 无法获取 token_id")
            return
        _run_single_highfreq(question, token_id, mode)


def run_all_highfreq_reports(slugs: list):
    for slug in slugs:
        for mode in ["1min", "5min"]:
            try:
                run_highfreq_report(slug, mode=mode)
            except Exception as e:
                send_text(f"❌ [{slug}] mode={mode} 报告失败: {e}")
                print(f"[report] 错误: {e}")


# ──────────────────────────────────────────
# 入口
# ──────────────────────────────────────────
if __name__ == "__main__":
    # 使用新的整合报告
    run_all_integrated_reports(SLUGS)
