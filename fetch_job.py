from datetime import datetime, timezone
from config import SLUGS
from fetcher import fetch_markets_batch
from notifier import send_text, send_template_card_report, upload_image
from report import build_integrated_report


def generate_summary_card(markets: dict) -> dict:
    """
    生成汇总卡片数据
    返回：{"title": "...", "sections": [...]}
    """
    valid_markets = {k: v for k, v in markets.items() if v is not None}
    
    if not valid_markets:
        return None
    
    sections = []
    for slug, m in valid_markets.items():
        if isinstance(m, list):
            m = m[0]
        
        question = m.get("question", slug)
        prices = m.get("outcomePrices", {})
        vol24 = m.get("volume24hr", 0)
        
        # 提取主要价格
        if "Yes" in prices:
            price_str = f"Yes: {prices['Yes']*100:.1f}%"
        elif len(prices) > 0:
            top = max(prices.items(), key=lambda x: x[1])
            price_str = f"{top[0]}: {top[1]*100:.1f}%"
        else:
            price_str = "无价格"
        
        # 格式化成交量
        vol_str = f"${vol24/1e6:.1f}M" if vol24 >= 1e6 else f"${vol24/1e3:.1f}K"
        
        sections.append({
            "title": question[:20] + "...",
            "content": f"{price_str} | 24h: {vol_str}"
        })
    
    return {
        "title": f"📊 市场监控汇总 ({len(valid_markets)} 个)",
        "summary": f"监控时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "sections": sections
    }


def run():
    print(f"[fetch_job] 开始执行 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    # ── 步骤 1：批量拉取市场数据 ──
    markets = fetch_markets_batch(SLUGS)

    # ── 步骤 2：发送汇总卡片 ──
    summary_card = generate_summary_card(markets)
    if summary_card:
        send_template_card_report(
            title=summary_card["title"],
            summary=summary_card["summary"],
            sections=summary_card["sections"]
        )
        print(f"[fetch_job] ✓ 汇总卡片已发送")

    # ── 步骤 3：逐条发送详细报告卡片 ──
    for idx, slug in enumerate(SLUGS, 1):
        try:
            print(f"\n[fetch_job] [{idx}/{len(SLUGS)}] 处理 {slug}")
            
            # 构建完整报告
            report_data = build_integrated_report(slug)
            if not report_data:
                print(f"[fetch_job] {slug} 无法生成报告")
                continue
            
            # 上传图表
            chart_media_ids = []
            for chart_bytes in report_data["charts"]:
                try:
                    media_id = upload_image(chart_bytes)
                    chart_media_ids.append(media_id)
                except Exception as e:
                    print(f"[fetch_job] 图表上传失败: {e}")
            
            # 构建卡片内容
            sections = [
                {"title": "📊 快照", "content": report_data["snapshot"][:50] + "..."}
            ]
            sections.extend(report_data["sections"])
            
            # 发送模板卡片
            send_template_card_report(
                title=report_data["title"],
                summary=f"包含 {len(report_data['charts'])} 个时间粒度分析",
                sections=sections,
                chart_media_ids=chart_media_ids
            )
            
            print(f"[fetch_job] ✓ {slug} 报告卡片已发送")
            
        except Exception as e:
            error_msg = f"❌ [{slug}] 报告失败: {str(e)}"
            send_text(error_msg)
            print(f"[fetch_job] {error_msg}")

    print(f"\n[fetch_job] 执行完毕 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")


if __name__ == "__main__":
    run()
