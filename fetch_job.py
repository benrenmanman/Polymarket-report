from datetime import datetime, timezone, timedelta
from config  import SLUGS
from fetcher import fetch_market
from db      import save_snapshot

def main():
    tz_bj     = timezone(timedelta(hours=8))
    timestamp = datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M 北京时间")

    for slug in SLUGS:
        slug = slug.strip()
        try:
            info              = fetch_market(slug)
            info["timestamp"] = timestamp
            save_snapshot(slug, info)
            print(f"✅ {slug} 快照已存储")
        except Exception as e:
            print(f"⚠️ {slug} 抓取失败：{e}")

main()
