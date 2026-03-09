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
from notifier import send_text, send_html, send_image


def generate_summary_header(slugs: list[str]) -> tuple[str, list[dict]]:
    """
    生成所有 slug 的概览汇总消息
    返回：(汇总文本, 市场详情列表)
    """
    all_markets = []
    
    for slug in slugs:
        try:
            result = fetch_market(slug)
            markets = result if isinstance(result, list) else [result]
            
            for m in markets:
                snapshot = {
                    "question": m.get("question", "未知问题"),
                    "slug": m.get("slug", slug),
                    "prices": m.get("outcomePrices", {}),
                    "volume24hr": m.get("volume24hr", 0),
                }
                all_markets.append(snapshot)
        except Exception as e:
            print(f"[report] 获取 {slug} 失败: {e}")
            continue
    
    if not all_markets:
        return "❌ 未获取到任何市场数据", []
    
    # 构建汇总消息
    header = f"📊 市场监控汇总 ({len(all_markets)} 个市场)\n"
    header += "━" * 40 + "\n\n"
    
    for idx, m in enumerate(all_markets, 1):
        prices = m["prices"]
        if "Yes" in prices:
            main_price = f"Yes: {prices['Yes']*100:.1f}%"
        elif len(prices) > 0:
            # 多选项市场，取最高概率
            top_outcome = max(prices.items(), key=lambda x: x[1])
            main_price = f"{top_outcome[0]}: {top_outcome[1]*100:.1f}%"
        else:
            main_price = "无价格"
        
        vol = m["volume24hr"]
        vol_str = f"${vol/1e6:.1f}M" if vol >= 1e6 else f"${vol/1e3:.1f}K"
        
        header += f"{idx}. {m['question']}\n"
        header += f"   💰 {main_price}  |  📊 24h: {vol_str}\n\n"
    
    header += "━" * 40 + "\n"
    header += "📝 详细报告将逐条发送...\n"
    
    return header, all_markets


def generate_report(slugs: list[str], mode: str = "1min"):
    """
    方案 A：先发汇总，再逐条发详细报告
    """
    print(f"[report] 开始生成报告，共 {len(slugs)} 个 slug")
    
    # ── 步骤 1：生成并发送汇总消息 ──
    summary_text, all_markets = generate_summary_header(slugs)
    send_text(summary_text)
    print(f"[report] 已发送汇总消息，包含 {len(all_markets)} 个市场")
    
    # ── 步骤 2：逐条发送详细报告 ──
    for idx, slug in enumerate(slugs, 1):
        try:
            print(f"\n[report] 处理 [{idx}/{len(slugs)}] {slug}")
            
            # 获取市场数据
            result = fetch_market(slug)
            markets = result if isinstance(result, list) else [result]
            
            for m in markets:
                question = m.get("question", "未知问题")
                token_id = m["clobTokenIds"][0] if "clobTokenIds" in m else None
                
                if not token_id:
                    print(f"[report] {question} 无 token_id，跳过")
                    continue
                
                # 快照分析
                snapshot_md = analyze_snapshot(m)
                send_html(snapshot_md)
                
                # 高频数据分析
                df = fetch_highfreq(token_id, mode=mode)
                if df.empty:
                    send_text(f"⚠️ {question}\n无高频数据")
                    continue
                
                # 统计摘要
                stats_md = summarize_highfreq(df, question)
                send_html(stats_md)
                
                # AI 分析
                analysis_md = analyze_highfreq(df, question)
                send_html(analysis_md)
                
                # 图表
                img_bytes = plot_highfreq(df, question)
                send_image(img_bytes, filename=f"{m.get('slug', 'chart')}.png")
                
                print(f"[report] ✓ {question} 报告已发送")
        
        except Exception as e:
            print(f"[report] ✗ {slug} 失败: {e}")
            send_text(f"❌ {slug} 报告生成失败：{str(e)}")
            continue
    
    print(f"[report] 全部报告发送完成")


# ── 保留原有的单个市场报告函数（向后兼容）──
def generate_single_report(slug: str, mode: str = "1min"):
    """
    单个市场报告（原有逻辑）
    """
    generate_report([slug], mode=mode)
