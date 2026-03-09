from datetime import datetime, timezone
from config import SLUGS
from fetcher import fetch_markets_batch
from report import build_summary_report
from notifier import send_markdown_v2, send_text


def run():
    print(f"[fetch_job] 开始执行 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    # 1. 批量拉取当前市场数据
    markets = fetch_markets_batch(SLUGS)

    # 2. 发送一条 markdown_v2 汇总消息（表格格式，简洁易读）
    try:
        summary_text = build_summary_report(markets)
        result = send_markdown_v2(summary_text)
        print(f"[fetch_job] 汇总消息已发送，返回：{result}")
    except Exception as e:
        send_text(f"❌ Polymarket 汇总报告发送失败: {e}")
        print(f"[fetch_job] 发送失败：{e}")

    print("[fetch_job] 执行完毕")


if __name__ == "__main__":
    run()
