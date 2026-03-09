from datetime import datetime, timezone, timedelta
from config import SLUGS
from fetcher import fetch_market, fetch_markets_batch
from notifier import send_text
from report import run_highfreq_report


def generate_summary_message(markets: dict) -> str:
    """
    生成所有市场的汇总消息
    参数：markets = {slug: market_data, ...}
    """
    valid_markets = {k: v for k, v in markets.items() if v is not None}
    
    if not valid_markets:
        return "❌ 未获取到任何市场数据"
    
    header = f"📊 市场监控汇总 ({len(valid_markets)} 个市场)\n"
    header += "━" * 40 + "\n\n"
    
    for idx, (slug, m) in enumerate(valid_markets.items(), 1):
        # 处理单市场或多选项市场
        if isinstance(m, list):
            # 多选项市场：显示所有选项
            question = m[0].get("question", slug).split(" - ")[0]  # 提取主问题
            header += f"{idx}. {question} (多选项)\n"
            
            for sub in m:
                sub_name = sub.get("question", "").split(" - ")[-1]  # 提取选项名
                prices = sub.get("outcomePrices", {})
                if "Yes" in prices:
                    price = prices["Yes"] * 100
                    header += f"   • {sub_name}: {price:.1f}%\n"
            header += "\n"
        else:
            # 单市场
            question = m.get("question", slug)
            prices = m.get("outcomePrices", {})
            vol24 = m.get("volume24hr", 0)
            
            # 提取主要价格
            if "Yes" in prices:
                main_price = f"Yes: {prices['Yes']*100:.1f}%"
            elif len(prices) > 0:
                top = max(prices.items(), key=lambda x: x[1])
                main_price = f"{top[0]}: {top[1]*100:.1f}%"
            else:
                main_price = "无价格"
            
            # 格式化成交量
            if vol24 >= 1e6:
                vol_str = f"${vol24/1e6:.1f}M"
            elif vol24 >= 1e3:
                vol_str = f"${vol24/1e3:.1f}K"
            else:
                vol_str = f"${vol24:.0f}"
            
            header += f"{idx}. {question}\n"
            header += f"   💰 {main_price}  |  📊 24h: {vol_str}\n\n"
    
    header += "━" * 40 + "\n"
    header += "📝 详细报告将逐条发送...\n"
    
    return header


def run():
    print(f"[fetch_job] 开始执行 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    # ── 步骤 1：批量拉取市场数据 ──
    markets = fetch_markets_batch(SLUGS)

    # ── 步骤 2：生成并发送汇总消息 ──
    summary = generate_summary_message(markets)
    send_text(summary)
    print(f"[fetch_job] ✓ 已发送汇总消息")

    # ── 步骤 3：逐条生成详细报告 ──
    for idx, slug in enumerate(SLUGS, 1):
        print(f"\n[fetch_job] [{idx}/{len(SLUGS)}] 开始处理 {slug}")
        
        # 对每个 slug 生成 1min 和 5min 两个粒度的报告
        for mode in ["1min", "5min"]:
            try:
                run_highfreq_report(slug, mode=mode)
                print(f"[fetch_job] ✓ {slug} ({mode}) 报告已发送")
            except Exception as e:
                error_msg = f"❌ [{slug}] {mode} 报告失败: {str(e)}"
                send_text(error_msg)
                print(f"[fetch_job] ✗ {error_msg}")

    print(f"\n[fetch_job] 执行完毕 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")


if __name__ == "__main__":
    run()
