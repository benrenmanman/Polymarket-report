from datetime import datetime, timezone, timedelta
from config   import SLUGS
from analyzer import ai_analyze
from db       import get_recent_snapshots
from notifier import send_feishu


def build_trend(rows: list[dict]) -> dict:
    """将多条快照转为趋势结构，喂给 ai_analyze"""
    count = len(rows)
    if count < 2:
        return {"count": count, "comparisons": {}}

    latest   = rows[-1]["data"]
    earliest = rows[0]["data"]
    mid      = rows[count // 2]["data"] if count >= 4 else None

    comparisons = {
        "最早快照": earliest,
        "最新快照": latest,
    }
    if mid:
        comparisons["中间快照"] = mid

    return {"count": count, "comparisons": comparisons}


def main():
    tz_bj     = timezone(timedelta(hours=8))
    timestamp = datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M 北京时间")
    results   = []

    for slug in SLUGS:
        slug = slug.strip()
        try:
            rows  = get_recent_snapshots(slug, limit=6)  # 最近1小时
            if not rows:
                print(f"⚠️ {slug} 暂无数据，跳过")
                continue

            info  = rows[-1]["data"]   # 最新一条作为当前数据
            trend = build_trend(rows)

            analysis = ai_analyze(info, trend)
            results.append(analysis)
            print(f"✅ {slug} 分析完成（共 {len(rows)} 条快照）")
        except Exception as e:
            print(f"⚠️ {slug} 分析失败：{e}")

    if results:
        full_report = "\n\n---\n\n".join(results)
        send_feishu(f"📊 **Polymarket 市场播报** `{timestamp}`\n\n{full_report}")


main()
