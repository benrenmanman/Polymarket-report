from datetime import datetime, timezone
from config   import SLUGS
from fetcher  import fetch_market
from analyzer import ai_analyze
from history  import load_history, save_history, append_snapshot, calc_trend
from notifier import send_feishu


def main():
    history   = load_history()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    results   = []

    for slug in SLUGS:
        slug = slug.strip()
        try:
            info              = fetch_market(slug)
            info["timestamp"] = timestamp

            trend   = calc_trend(slug, history)
            history = append_snapshot(history, slug, info)

            analysis = ai_analyze(info, trend)
            results.append(analysis)
            print(f"✅ {slug} 处理完成（历史共 {len(history[slug])} 条）")
        except Exception as e:
            print(f"⚠️ {slug} 处理失败：{e}")

    if results:
        full_report = "\n\n---\n\n".join(results)
        send_feishu(f"📊 **Polymarket 市场播报** `{timestamp}`\n\n{full_report}")

    save_history(history)


main()
