from datetime import datetime, timezone, timedelta
from config import SLUGS
from fetcher import fetch_market, fetch_markets_batch
from history import fetch_highfreq
from report import build_report
from notifier import send_text


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
            m = m[0]  # 取第一个子市场作为代表
        
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
    print(f"[fetch_job] 已发送汇总消息")

    # ── 步骤 3：逐条生成详细报告 ──
    for idx, slug in enumerate(SLUGS, 1):
        try:
            market = markets.get(slug)
            if not market:
                print(f"[fetch_job] [{idx}/{len(SLUGS)}] {slug} 未获取到市场数据，跳过")
                continue

            print(f"[fetch_job] [{idx}/{len(SLUGS)}] 处理 {slug}")

            # 直接从 API 拉取高频数据，不缓存
            df_1min = fetch_highfreq(slug, mode="1min")
            df_5min = fetch_highfreq(slug, mode="5min")

            # 生成并发送报告
            build_report(slug, market, df_1min, df_5min)

        except Exception as e:
            print(f"[fetch_job] [{idx}/{len(SLUGS)}] {slug} 处理失败：{e}")
            send_text(f"❌ {slug} 报告生成失败：{str(e)}")

    print("[fetch_job] 执行完毕")


if __name__ == "__main__":
    run()
