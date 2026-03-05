import requests
import json
import os
from datetime import datetime, timezone
from openai import OpenAI

# ── 必须先读环境变量，再初始化 client ──
FEISHU_WEBHOOK  = os.environ["FEISHU_WEBHOOK"]
OPENAI_API_KEY  = os.environ["OPENAI_API_KEY"]
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL    = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
SLUGS = os.environ.get("MARKET_SLUGS", "what-price-will-bitcoin-hit-in-2025").split(",")

# ── 读完变量之后才能初始化 client ──
client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

# ── 1. 拉取 Polymarket 数据 ───────────────────────────────
def fetch_market(slug: str) -> dict:
    slug = slug.strip()
    url  = f"https://gamma-api.polymarket.com/events?slug={slug}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data:
        return data[0]

    url2  = f"https://gamma-api.polymarket.com/markets?slug={slug}"
    resp2 = requests.get(url2, timeout=30)
    resp2.raise_for_status()
    data2 = resp2.json()
    return data2[0] if data2 else {}

# ── 2. 提取关键字段 ───────────────────────────────────────
def extract_key_info(raw: dict) -> dict:
    markets = []
    for m in raw.get("markets", []):
        outcomes = json.loads(m.get("outcomes", "[]"))
        prices   = json.loads(m.get("outcomePrices", "[]"))
        markets.append({
            "question": m.get("question"),
            "options":  dict(zip(outcomes, prices)),
            "volume_M": round(m.get("volumeNum", 0) / 1e6, 2),
            "closed":   m.get("closed"),
        })
    return {
        "title":          raw.get("title"),
        "closed":         raw.get("closed"),
        "volume_total_M": round(raw.get("volume", 0) / 1e6, 2),
        "volume_1wk_M":   round(raw.get("volume1wk", 0) / 1e6, 2),
        "markets":        markets,
    }

# ── 3. AI 分析 ────────────────────────────────────────────
def ai_analyze(info: dict, trend: dict) -> str:
    count = trend.get("count", 0)
    comparisons = trend.get("comparisons", {})

    # 动态生成趋势说明
    if count < 2:
        trend_block = "⚠️ 首次记录，暂无历史趋势，禁止编造任何对比数据。"
    else:
        available = list(comparisons.keys())
        trend_block = f"""
以下是基于真实历史快照的趋势数据（共 {count} 条记录），
可用对比维度：{', '.join(available)}

{json.dumps(comparisons, ensure_ascii=False, indent=2)}

⚠️ 只能使用以上维度进行对比，不得提及不存在的时间维度。
"""

    prompt = f"""
你是专业预测市场分析师，请严格基于以下数据撰写播报，禁止编造数据。

【当前市场数据】
{json.dumps(info, ensure_ascii=False, indent=2)}

【趋势对比数据】
{trend_block}

输出格式（Markdown）：
1. 📌 市场标题 + 当前最高概率选项
2. 📊 各选项概率
3. 📈 趋势分析：
   - 有哪些维度的数据就分析哪些，没有的不提
   - 变化超过 5% 的选项重点标注 ⚠️
4. 💡 市场情绪判断（2~3句）
5. 💰 各维度交易量变化
"""

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "你是专业预测市场分析师，只基于提供的数据分析，不编造任何数字。"},
            {"role": "user",   "content": prompt}
        ],
        temperature=0.7,
        max_tokens=1200,
    )
    return response.choices[0].message.content.strip()

# ── 5. 读取并存储数据 ───────────────────────────────────
HISTORY_FILE = "history.json"
MAX_SNAPSHOTS = 2016  # 保留最近 2016 条 = 30分钟间隔下约 6 周数据

def load_history() -> dict:
    """读取完整历史时间轴"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_history(history: dict):
    """保存历史，每个 slug 保留最近 MAX_SNAPSHOTS 条"""
    for slug in history:
        if len(history[slug]) > MAX_SNAPSHOTS:
            history[slug] = history[slug][-MAX_SNAPSHOTS:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def append_snapshot(history: dict, slug: str, info: dict) -> dict:
    """把本次数据追加到该 slug 的历史数组"""
    if slug not in history:
        history[slug] = []
    
    snapshot = {
        "timestamp": info["timestamp"],
        "outcomes":  info.get("outcomes", []),
        "volume":    info.get("volume", 0),
    }
    history[slug].append(snapshot)
    return history

# ── 6. 对比历史数据，计算变化趋势 ───────────────────────────────────
def calc_trend(slug: str, history: dict) -> dict:
    """从历史时间轴提取多维度趋势"""
    snapshots = history.get(slug, [])
    count = len(snapshots)
    
    if count < 2:
        return {"status": "首次记录，暂无趋势数据", "count": count}

    trend = {"count": count, "comparisons": {}}
    latest = snapshots[-1]

    # 定义对比维度：名称 → 往前取第几条
    intervals = {}
    if count >= 2:   intervals["30分钟前"] = snapshots[-2]
    if count >= 48:  intervals["24小时前"] = snapshots[-48]
    if count >= 336: intervals["7天前"]   = snapshots[-336]
    if count >= 1440:intervals["30天前"]  = snapshots[-1440]

    latest_probs = {o["title"]: o["probability"] for o in latest["outcomes"]}

    for label, old_snap in intervals.items():
        old_probs = {o["title"]: o["probability"] for o in old_snap["outcomes"]}
        changes = []
        for title, curr_prob in latest_probs.items():
            old_prob = old_probs.get(title, curr_prob)
            delta = round(curr_prob - old_prob, 4)
            arrow = "📈" if delta > 0.01 else ("📉" if delta < -0.01 else "➡️")
            changes.append({
                "option":  title,
                "old":     f"{old_prob*100:.1f}%",
                "current": f"{curr_prob*100:.1f}%",
                "delta":   f"{delta*100:+.1f}%",
                "arrow":   arrow
            })
        
        vol_delta = latest["volume"] - old_snap["volume"]
        trend["comparisons"][label] = {
            "from_timestamp": old_snap["timestamp"],
            "changes":        changes,
            "volume_delta":   f"{vol_delta:+.0f} USDC"
        }

    return trend

# ── 4. 推送飞书消息卡片 ───────────────────────────────────
def send_feishu(text: str):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    payload = {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "📊 Polymarket AI 播报"
                },
                "template": "blue"
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": text
                    },
                    {
                        "tag": "hr"
                    },
                    {
                        "tag": "markdown",
                        "content": f"🕐 更新时间：{now}"
                    }
                ]
            }
        }
    }

    r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=15)
    r.raise_for_status()
    result = r.json()

    if result.get("code") != 0 and result.get("StatusCode") != 0:
        raise Exception(f"飞书推送失败：{result}")


# ── 5. 主流程 ─────────────────────────────────────────────
def main():
    history = load_history()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    results = []

    for slug in SLUGS:
        slug = slug.strip()
        try:
            info = fetch_market(slug)
            info["timestamp"] = timestamp

            # 先计算趋势（用追加前的历史）
            trend = calc_trend(slug, history)

            # 再追加本次快照
            history = append_snapshot(history, slug, info)

            analysis = ai_analyze(info, trend)
            results.append(analysis)
            print(f"✅ {slug} 处理完成（历史共 {len(history[slug])} 条）")
        except Exception as e:
            print(f"⚠️ {slug} 处理失败：{e}")

    if results:
        full_report = "\n\n---\n\n".join(results)
        send_feishu(f"📊 **Polymarket 市场播报** `{timestamp}`\n\n{full_report}")

    # 保存追加后的完整历史
    save_history(history)

main()
