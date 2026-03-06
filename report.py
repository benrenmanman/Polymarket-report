from datetime import datetime, timezone, timedelta
from config   import SLUGS
from analyzer import ai_analyze
from db       import get_snapshot_at, get_latest_snapshot
from notifier import send_wecom   # ← 替换 send_feishu


def build_trend(slug: str, tz_bj) -> dict:
    """
    精确取4个时间节点：
    - 最新：数据库最新一条
    - 上次：上一条（约10分钟前）
    - 上周：约7天前最近一条
    - 上月：约30天前最近一条
    """
    now = datetime.now(timezone.utc)

    latest    = get_latest_snapshot(slug)
    last      = get_snapshot_at(slug, now - timedelta(minutes=10))
    last_week = get_snapshot_at(slug, now - timedelta(days=7))
    last_month= get_snapshot_at(slug, now - timedelta(days=30))

    snapshots = {}

    if latest:
        snapshots["最新"] = latest["data"]
    if last and last.get("id") != (latest or {}).get("id"):
        snapshots["上次（约10分钟前）"] = last["data"]
    if last_week:
        snapshots["上周同期"] = last_week["data"]
    if last_month:
        snapshots["上月同期"] = last_month["data"]

    return {
        "count": len(snapshots),
        "comparisons": snapshots
    }


def main():
    tz_bj     = timezone(timedelta(hours=8))
    timestamp = datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M 北京时间")
    results   = []

    for slug in SLUGS:
        slug = slug.strip()
        try:
            latest = get_latest_snapshot(slug)
            if not latest:
                print(f"⚠️ {slug} 暂无数据，跳过")
                continue

            info  = latest["data"]
            trend = build_trend(slug, tz_bj)

            analysis = ai_analyze(info, trend)
            results.append(analysis)
            print(f"✅ {slug} 分析完成（快照维度：{list(trend['comparisons'].keys())}）")
        except Exception as e:
            print(f"⚠️ {slug} 分析失败：{e}")

    if results:
        full_report = "\n\n---\n\n".join(results)
        send_wecom(f"📊 **Polymarket 市场播报** `{timestamp}`\n\n{full_report}")


main()
