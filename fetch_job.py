from datetime import datetime, timezone, timedelta
from config import SLUGS
from fetcher import fetch_market, fetch_markets_batch
from history import fetch_highfreq
from report import build_report


def run():
    print(f"[fetch_job] 开始执行 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    # 批量拉取当前市场数据
    markets = fetch_markets_batch(SLUGS)

    for slug in SLUGS:
        try:
            market = markets.get(slug)
            if not market:
                print(f"[fetch_job] {slug} 未获取到市场数据，跳过")
                continue

            # 直接从 API 拉取高频数据，不缓存
            df_1min = fetch_highfreq(slug, mode="1min")
            df_1day = fetch_highfreq(slug, mode="1day")

            # 生成并发送报告
            build_report(slug, market, df_1min, df_1day)

        except Exception as e:
            print(f"[fetch_job] {slug} 处理失败：{e}")

    print("[fetch_job] 执行完毕")


if __name__ == "__main__":
    run()
