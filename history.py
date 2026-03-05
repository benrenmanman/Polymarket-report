import json
import os
from config import HISTORY_FILE, MAX_SNAPSHOTS


def load_history() -> dict:
    if not os.path.exists(HISTORY_FILE):
        print("📂 history.json 不存在，将创建新文件")
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"📂 已加载历史数据，共 {len(data)} 个市场")
        return data
    except json.JSONDecodeError as e:
        print(f"⚠️ history.json 解析失败：{e}，将重置为空")
        return {}


def save_history(history: dict):
    tmp_file = HISTORY_FILE + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, HISTORY_FILE)
        total = sum(len(v) for v in history.values())
        print(f"💾 history.json 已保存，共 {len(history)} 个市场 / {total} 条快照")
    except Exception as e:
        print(f"❌ 保存 history.json 失败：{e}")
        if os.path.exists(tmp_file):
            os.remove(tmp_file)


def build_snapshot(info: dict) -> dict:
    active_markets = [
        m for m in info.get("markets", [])
        if not m.get("archived", False) and not m.get("closed", False)
    ]

    markets_snapshot = []
    for m in active_markets:
        raw_prices = m.get("outcomePrices", "[]")
        if isinstance(raw_prices, str):
            try:
                prices_list = json.loads(raw_prices)
                outcome_prices = {
                    "Yes": float(prices_list[0]),
                    "No":  float(prices_list[1])
                }
            except Exception:
                outcome_prices = {}
        elif isinstance(raw_prices, dict):
            outcome_prices = raw_prices
        else:
            outcome_prices = {}

        markets_snapshot.append({
            "id":                  m.get("id", ""),
            "question":            m.get("question", ""),
            "slug":                m.get("slug", ""),
            "active":              m.get("active", False),
            "closed":              m.get("closed", False),
            "outcomePrices":       outcome_prices,
            "volume":              m.get("volumeNum", m.get("volume", 0)),
            "volume24hr":          m.get("volume24hr", 0),
            "lastTradePrice":      m.get("lastTradePrice", 0),
            "bestBid":             m.get("bestBid", 0),
            "bestAsk":             m.get("bestAsk", 0),
            "oneDayPriceChange":   m.get("oneDayPriceChange",   None),
            "oneWeekPriceChange":  m.get("oneWeekPriceChange",  None),
            "oneMonthPriceChange": m.get("oneMonthPriceChange", None),
        })

    return {
        "timestamp":  info.get("timestamp", ""),
        "volume":     info.get("volume",     0),
        "volume24hr": info.get("volume24hr", 0),
        "markets":    markets_snapshot,
    }


def append_snapshot(history: dict, slug: str, info: dict) -> dict:
    if slug not in history:
        history[slug] = []

    history[slug].append(build_snapshot(info))

    if len(history[slug]) > MAX_SNAPSHOTS:
        history[slug] = history[slug][-MAX_SNAPSHOTS:]
        print(f"✂️  {slug} 历史超过 {MAX_SNAPSHOTS} 条，已裁剪旧数据")

    return history


def get_prices(snap: dict) -> dict:
    return {
        m["question"]: m.get("outcomePrices", {})
        for m in snap.get("markets", [])
    }


def calc_trend(slug: str, history: dict) -> dict:
    snapshots = history.get(slug, [])
    count     = len(snapshots)

    if count < 2:
        return {"status": "首次记录，暂无趋势数据", "count": count}

    trend  = {"count": count, "comparisons": {}}
    latest = snapshots[-1]

    intervals = {}
    if count >= 2:    intervals["30分钟前"] = snapshots[-2]
    if count >= 48:   intervals["24小时前"] = snapshots[-48]
    if count >= 336:  intervals["7天前"]    = snapshots[-336]
    if count >= 1440: intervals["30天前"]   = snapshots[-1440]

    latest_prices = get_prices(latest)

    for label, old_snap in intervals.items():
        old_prices = get_prices(old_snap)
        changes    = []

        for question, curr_opts in latest_prices.items():
            old_opts = old_prices.get(question, curr_opts)
            for option, curr_prob in curr_opts.items():
                old_prob = old_opts.get(option, curr_prob)
                try:
                    curr_f = float(curr_prob)
                    old_f  = float(old_prob)
                except (TypeError, ValueError):
                    continue
                delta = round(curr_f - old_f, 4)
                arrow = "📈" if delta > 0.01 else ("📉" if delta < -0.01 else "➡️")
                changes.append({
                    "question": question,
                    "option":   option,
                    "old":      f"{old_f  * 100:.1f}%",
                    "current":  f"{curr_f * 100:.1f}%",
                    "delta":    f"{delta  * 100:+.1f}%",
                    "arrow":    arrow
                })

        vol_delta = latest.get("volume", 0) - old_snap.get("volume", 0)
        trend["comparisons"][label] = {
            "from_timestamp": old_snap.get("timestamp", ""),
            "changes":        changes,
            "volume_delta":   f"{vol_delta:+.0f} USDC"
        }

    return trend
